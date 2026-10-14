"""SQS long-poll worker with idempotency, backoff+jitter, and graceful shutdown.

Permanent errors (validation, missing object) are left on the queue so SQS
redrive (`maxReceiveCount`) moves them to the DLQ. Visibility is shortened so
poison messages reach the DLQ quickly instead of occupying in-flight slots
for the full visibility timeout.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import signal
import time
from typing import Any

from botocore.exceptions import ClientError

from docproc import aws
from docproc.config import Settings, get_settings
from docproc.idempotency import ClaimResult, IdempotencyStore
from docproc.logging import (
    configure_logging,
    document_id_var,
    log_extra,
    receive_count_var,
)
from docproc.models import QueueMessage

logger = logging.getLogger("docproc.worker")

MAX_BACKOFF_SECONDS = 900
PERMANENT_VISIBILITY_SECONDS = 5
LONG_POLL_SECONDS = 20
MAX_MESSAGES = 10


class PermanentError(Exception):
    """Do not retry with long backoff; let SQS redrive to the DLQ."""


class TransientError(Exception):
    """Retry with exponential backoff + full jitter via ChangeMessageVisibility."""


_shutdown = False


def _handle_signal(signum: int, _frame: object | None) -> None:
    global _shutdown
    logger.info("signal_received", extra=log_extra(signum=signum))
    _shutdown = True


def backoff_seconds(receive_count: int, cap: int = MAX_BACKOFF_SECONDS) -> int:
    """Full jitter: sleep in [1, min(cap, 2^receive_count)]."""
    ceiling = min(cap, 2 ** max(receive_count, 1))
    return random.randint(1, max(1, ceiling))


def _parse_message(body: str) -> QueueMessage:
    try:
        return QueueMessage.model_validate_json(body)
    except Exception as exc:
        raise PermanentError(f"invalid message body: {exc}") from exc


def _process_document(settings: Settings, message: QueueMessage) -> dict[str, Any]:
    if settings.processing_delay_seconds:
        time.sleep(settings.processing_delay_seconds)
    if settings.failure_rate > 0 and random.random() < settings.failure_rate:
        raise TransientError("injected failure")
    try:
        payload = aws.get_object_bytes(settings, message.s3_key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise PermanentError(f"missing object {message.s3_key}") from exc
        if aws.is_transient(exc):
            raise TransientError(str(exc)) from exc
        raise PermanentError(str(exc)) from exc
    digest = hashlib.sha256(payload).hexdigest()
    if digest != message.sha256:
        raise PermanentError("sha256 mismatch")
    result = {
        "document_id": message.document_id,
        "s3_key": message.s3_key,
        "sha256": digest,
        "bytes": len(payload),
        "content_type": message.content_type,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "processed",
    }
    aws.put_object_bytes(
        settings,
        key=f"processed/{message.document_id}.json",
        body=json.dumps(result).encode("utf-8"),
        content_type="application/json",
        metadata={"document-id": message.document_id},
    )
    return result


def process_one(
    settings: Settings,
    store: IdempotencyStore,
    sqs_message: dict[str, Any],
) -> str:
    """Handle a single SQS message. Returns an outcome label for tests."""
    receipt = sqs_message["ReceiptHandle"]
    receive_count = int(sqs_message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    receive_token = receive_count_var.set(receive_count)
    document_token = None
    started = time.perf_counter()
    try:
        parsed = _parse_message(sqs_message["Body"])
        document_token = document_id_var.set(parsed.document_id)
        claim = store.claim(parsed.document_id)
        if claim is ClaimResult.ALREADY_COMPLETED:
            aws.sqs_client(settings).delete_message(
                QueueUrl=settings.queue_url, ReceiptHandle=receipt
            )
            logger.info("idempotency_skip", extra=log_extra(outcome="already_completed"))
            return "skipped"
        if claim is ClaimResult.IN_PROGRESS:
            timeout = backoff_seconds(receive_count)
            aws.sqs_client(settings).change_message_visibility(
                QueueUrl=settings.queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=timeout,
            )
            logger.info("idempotency_in_progress", extra=log_extra(visibility=timeout))
            return "in_progress"
        result = _process_document(settings, parsed)
        store.complete(parsed.document_id)
        aws.sqs_client(settings).delete_message(QueueUrl=settings.queue_url, ReceiptHandle=receipt)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "processed",
            extra={"duration_ms": duration_ms, "extra_fields": {"bytes": result["bytes"]}},
        )
        return "processed"
    except PermanentError as exc:
        aws.sqs_client(settings).change_message_visibility(
            QueueUrl=settings.queue_url,
            ReceiptHandle=receipt,
            VisibilityTimeout=PERMANENT_VISIBILITY_SECONDS,
        )
        logger.error(
            "permanent_error",
            extra={"error_type": "permanent", "extra_fields": {"error": str(exc)}},
        )
        return "permanent"
    except (TransientError, ClientError) as exc:
        if isinstance(exc, ClientError) and not aws.is_transient(exc):
            aws.sqs_client(settings).change_message_visibility(
                QueueUrl=settings.queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=PERMANENT_VISIBILITY_SECONDS,
            )
            logger.error(
                "permanent_error",
                extra={"error_type": "permanent", "extra_fields": {"error": str(exc)}},
            )
            return "permanent"
        timeout = backoff_seconds(receive_count)
        aws.sqs_client(settings).change_message_visibility(
            QueueUrl=settings.queue_url,
            ReceiptHandle=receipt,
            VisibilityTimeout=timeout,
        )
        logger.warning(
            "transient_error",
            extra={
                "error_type": "transient",
                "extra_fields": {"error": str(exc), "visibility": timeout},
            },
        )
        return "transient"
    finally:
        receive_count_var.reset(receive_token)
        if document_token is not None:
            document_id_var.reset(document_token)


def run_loop(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    store = IdempotencyStore(settings)
    client = aws.sqs_client(settings)
    logger.info("worker_start", extra=log_extra(queue=settings.queue_url))
    while not _shutdown:
        response = client.receive_message(
            QueueUrl=settings.queue_url,
            MaxNumberOfMessages=MAX_MESSAGES,
            WaitTimeSeconds=LONG_POLL_SECONDS,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        for message in messages:
            if _shutdown:
                logger.info("draining_stop")
                break
            process_one(settings, store, message)
    logger.info("worker_stop")


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()

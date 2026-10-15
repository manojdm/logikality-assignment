"""SQS long-poll worker with lease-based idempotency, backoff+jitter, and SIGTERM drain.

Permanent errors (validation, missing object) are left on the queue so SQS
redrive (`maxReceiveCount`) moves them to the DLQ. Visibility is shortened so
poison messages reach the DLQ quickly. Failed claims are released so a
redelivery can take a new lease.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import signal
import threading
import time
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

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
    receipt = str(sqs_message["ReceiptHandle"])
    receive_count = int(sqs_message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    receive_token = receive_count_var.set(receive_count)
    document_token = None
    claimed = False
    claimed_id: str | None = None
    started = time.perf_counter()

    def _set_visibility(seconds: int) -> None:
        aws.sqs_client(settings).change_message_visibility(
            QueueUrl=settings.queue_url,
            ReceiptHandle=receipt,
            VisibilityTimeout=seconds,
        )

    def _fail(kind: str, exc: BaseException, seconds: int) -> str:
        if claimed and claimed_id is not None:
            store.release(claimed_id)
        _set_visibility(seconds)
        logger.log(
            logging.ERROR if kind == "permanent" else logging.WARNING,
            f"{kind}_error",
            extra=log_extra(error_type=kind, error=str(exc), visibility=seconds),
        )
        return kind

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
            _set_visibility(timeout)
            logger.info("idempotency_in_progress", extra=log_extra(visibility=timeout))
            return "in_progress"
        claimed = True
        claimed_id = parsed.document_id
        result = _process_document(settings, parsed)
        store.complete(parsed.document_id)
        aws.sqs_client(settings).delete_message(QueueUrl=settings.queue_url, ReceiptHandle=receipt)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info("processed", extra=log_extra(bytes=result["bytes"], duration_ms=duration_ms))
        return "processed"
    except PermanentError as exc:
        return _fail("permanent", exc, PERMANENT_VISIBILITY_SECONDS)
    except (TransientError, ClientError) as exc:
        if isinstance(exc, ClientError) and not aws.is_transient(exc):
            return _fail("permanent", exc, PERMANENT_VISIBILITY_SECONDS)
        return _fail("transient", exc, backoff_seconds(receive_count))
    finally:
        receive_count_var.reset(receive_token)
        if document_token is not None:
            document_id_var.reset(document_token)


class Worker:
    """Long-poll loop. Stop via `stop.set()` or SIGTERM/SIGINT."""

    def __init__(
        self,
        settings: Settings,
        store: IdempotencyStore | None = None,
        stop: threading.Event | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or IdempotencyStore(settings)
        self.stop = stop or threading.Event()

    def request_stop(self, signum: int = 0) -> None:
        logger.info("signal_received", extra=log_extra(signum=signum))
        self.stop.set()

    def run(self) -> None:
        client = aws.sqs_client(self.settings)
        logger.info("worker_start", extra=log_extra(queue=self.settings.queue_url))
        while not self.stop.is_set():
            try:
                response = client.receive_message(
                    QueueUrl=self.settings.queue_url,
                    MaxNumberOfMessages=MAX_MESSAGES,
                    WaitTimeSeconds=LONG_POLL_SECONDS,
                    AttributeNames=["All"],
                    MessageAttributeNames=["All"],
                )
            except (BotoCoreError, ClientError) as exc:
                logger.warning("receive_failed", extra=log_extra(error=str(exc)))
                self.stop.wait(1)
                continue
            messages = response.get("Messages", [])
            for message in messages:
                if self.stop.is_set():
                    logger.info("draining_stop")
                    break
                process_one(self.settings, self.store, dict(message))
        logger.info("worker_stop")


def run_loop(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    worker = Worker(settings)

    def _handle(signum: int, _frame: object | None) -> None:
        worker.request_stop(signum)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    worker.run()


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()

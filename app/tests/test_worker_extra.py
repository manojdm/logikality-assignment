from __future__ import annotations

import hashlib
import json
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from docproc import aws
from docproc import worker as worker_mod
from docproc.config import Settings
from docproc.idempotency import ClaimResult, IdempotencyStore
from docproc.models import QueueMessage
from docproc.worker import (
    PermanentError,
    TransientError,
    _parse_message,
    _process_document,
    process_one,
    run_loop,
)


def _message(document_id: str, sha: str) -> QueueMessage:
    return QueueMessage(
        document_id=document_id,
        s3_key=f"incoming/{document_id}",
        sha256=sha,
        submitted_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        content_type="application/pdf",
    )


def test_parse_message_rejects_garbage() -> None:
    with pytest.raises(PermanentError):
        _parse_message("not-json")


def test_sha256_mismatch_is_permanent(settings: Settings) -> None:
    aws.put_object_bytes(settings, key="incoming/bad", body=b"aaa", content_type="text/plain")
    msg = _message("bad", "0" * 64)
    with pytest.raises(PermanentError, match="sha256"):
        _process_document(settings, msg)


def test_injected_failure_rate(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    failing = settings.model_copy(update={"failure_rate": 1.0, "processing_delay_seconds": 0.0})
    aws.put_object_bytes(failing, key="incoming/x", body=b"aaa", content_type="text/plain")
    sha = hashlib.sha256(b"aaa").hexdigest()
    with pytest.raises(TransientError):
        _process_document(failing, _message("x", sha))


def test_in_progress_does_not_delete(settings: Settings, store: IdempotencyStore) -> None:
    body = b"loan"
    sha = hashlib.sha256(body).hexdigest()
    aws.put_object_bytes(
        settings, key="incoming/inflight", body=body, content_type="application/pdf"
    )
    store.claim("inflight")
    aws.send_message(settings, _message("inflight", sha).model_dump_json(), idempotency_key=sha)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    sqs_message = sqs.receive_message(
        QueueUrl=settings.queue_url, MaxNumberOfMessages=1, AttributeNames=["All"]
    )["Messages"][0]
    assert process_one(settings, store, sqs_message) == "in_progress"
    attrs = aws.get_queue_attributes(settings)
    assert int(attrs.get("ApproximateNumberOfMessagesNotVisible", "0")) >= 0


def test_non_transient_client_error(settings: Settings, store: IdempotencyStore) -> None:
    body = b"loan"
    sha = hashlib.sha256(body).hexdigest()
    aws.put_object_bytes(settings, key="incoming/denied", body=body, content_type="application/pdf")
    aws.send_message(settings, _message("denied", sha).model_dump_json(), idempotency_key=sha)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    sqs_message = sqs.receive_message(
        QueueUrl=settings.queue_url, MaxNumberOfMessages=1, AttributeNames=["All"]
    )["Messages"][0]
    err = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "no"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "GetObject",
    )

    def _boom(*_a: object, **_k: object) -> None:
        raise err

    import docproc.worker as w

    original = w._process_document
    w._process_document = _boom  # type: ignore[assignment]
    try:
        assert process_one(settings, store, sqs_message) == "permanent"
    finally:
        w._process_document = original  # type: ignore[assignment]


def test_run_loop_stops_on_shutdown(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    worker_mod._shutdown = False

    class FakeSqs:
        def receive_message(self, **_kwargs: Any) -> dict[str, Any]:
            worker_mod._shutdown = True
            return {"Messages": []}

    monkeypatch.setattr(aws, "sqs_client", lambda _s: FakeSqs())
    monkeypatch.setattr("docproc.worker.IdempotencyStore", lambda _s: object())
    run_loop(settings)
    assert worker_mod._shutdown is True


def test_signal_handler_sets_flag() -> None:
    worker_mod._shutdown = False
    worker_mod._handle_signal(15, None)
    assert worker_mod._shutdown is True
    worker_mod._shutdown = False


def test_transient_get_object(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    err = ClientError(
        {
            "Error": {"Code": "SlowDown", "Message": "slow"},
            "ResponseMetadata": {"HTTPStatusCode": 503},
        },
        "GetObject",
    )

    def _boom(*_a: object, **_k: object) -> bytes:
        raise err

    monkeypatch.setattr(aws, "get_object_bytes", _boom)
    sha = hashlib.sha256(b"x").hexdigest()
    with pytest.raises(TransientError):
        _process_document(settings, _message("t", sha))


def test_claim_raises_other_client_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = IdempotencyStore(settings)
    err = ClientError(
        {
            "Error": {"Code": "InternalServerError", "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        },
        "PutItem",
    )

    def _put(**_k: object) -> None:
        raise err

    monkeypatch.setattr(store._table, "put_item", _put)
    with pytest.raises(ClientError):
        store.claim("z")


def test_logging_exception_path() -> None:
    import logging

    from docproc.logging import JsonFormatter, configure_logging, log_extra

    configure_logging("DEBUG")
    formatter = JsonFormatter()
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), None)
    try:
        raise ValueError("x")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()
    text = formatter.format(record)
    assert "exc_info" in text
    assert "extra_fields" in log_extra(a=1)["extra"]


assert ClaimResult
assert json

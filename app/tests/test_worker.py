from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError

from docproc import aws
from docproc.config import Settings
from docproc.idempotency import IdempotencyStore
from docproc.logging import JsonFormatter, configure_logging, log_extra
from docproc.models import QueueMessage
from docproc.worker import (
    PermanentError,
    TransientError,
    Worker,
    _parse_message,
    _process_document,
    backoff_seconds,
    process_one,
    run_loop,
)


def _enqueue(settings: Settings, document_id: str, body: bytes, sha256: str) -> dict[str, str]:
    aws.put_object_bytes(
        settings,
        key=f"incoming/{document_id}",
        body=body,
        content_type="application/pdf",
    )
    message = QueueMessage(
        document_id=document_id,
        s3_key=f"incoming/{document_id}",
        sha256=sha256,
        submitted_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        content_type="application/pdf",
    )
    aws.send_message(settings, message.model_dump_json(), content_sha256=sha256)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    received = sqs.receive_message(
        QueueUrl=settings.queue_url,
        MaxNumberOfMessages=1,
        AttributeNames=["All"],
    )
    return received["Messages"][0]  # type: ignore[no-any-return]


def _message(document_id: str, sha: str) -> QueueMessage:
    return QueueMessage(
        document_id=document_id,
        s3_key=f"incoming/{document_id}",
        sha256=sha,
        submitted_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        content_type="application/pdf",
    )


def test_happy_path_writes_processed(settings: Settings, store: IdempotencyStore) -> None:
    body = b"loan-application"
    sha = hashlib.sha256(body).hexdigest()
    sqs_message = _enqueue(settings, "doc-1", body, sha)
    outcome = process_one(settings, store, sqs_message)
    assert outcome == "processed"
    s3 = boto3.client("s3", region_name=settings.aws_region)
    processed = s3.get_object(Bucket=settings.document_bucket, Key="processed/doc-1.json")
    payload = json.loads(processed["Body"].read())
    assert payload["document_id"] == "doc-1"
    leftover = boto3.client("sqs", region_name=settings.aws_region).receive_message(
        QueueUrl=settings.queue_url, WaitTimeSeconds=0, MaxNumberOfMessages=1
    )
    assert leftover.get("Messages") is None


def test_duplicate_message_skipped_once(settings: Settings, store: IdempotencyStore) -> None:
    body = b"loan-application"
    sha = hashlib.sha256(body).hexdigest()
    first = _enqueue(settings, "doc-dup", body, sha)
    assert process_one(settings, store, first) == "processed"

    sqs = boto3.client("sqs", region_name=settings.aws_region)
    aws.send_message(
        settings,
        QueueMessage(
            document_id="doc-dup",
            s3_key="incoming/doc-dup",
            sha256=sha,
            submitted_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            content_type="application/pdf",
        ).model_dump_json(),
        content_sha256=sha,
    )
    second = sqs.receive_message(
        QueueUrl=settings.queue_url, MaxNumberOfMessages=1, AttributeNames=["All"]
    )["Messages"][0]
    assert process_one(settings, store, second) == "skipped"
    s3 = boto3.client("s3", region_name=settings.aws_region)
    listed = s3.list_objects_v2(Bucket=settings.document_bucket, Prefix="processed/")
    assert listed["KeyCount"] == 1


def test_transient_error_does_not_delete(
    settings: Settings, store: IdempotencyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"loan-application"
    sha = hashlib.sha256(body).hexdigest()
    sqs_message = _enqueue(settings, "doc-retry", body, sha)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise TransientError("downstream 429")

    monkeypatch.setattr("docproc.worker._process_document", _boom)
    outcome = process_one(settings, store, sqs_message)
    assert outcome == "transient"
    attrs = aws.get_queue_attributes(settings)
    visible = int(attrs.get("ApproximateNumberOfMessages", "0"))
    in_flight = int(attrs.get("ApproximateNumberOfMessagesNotVisible", "0"))
    assert visible + in_flight == 1


def test_transient_failure_then_redelivery_processed_once(
    settings: Settings, store: IdempotencyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"loan-application"
    sha = hashlib.sha256(body).hexdigest()
    first = _enqueue(settings, "doc-once", body, sha)
    calls = {"n": 0}

    def _flaky(settings_arg: Settings, message: QueueMessage) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientError("injected")
        return _process_document(settings_arg, message)

    monkeypatch.setattr("docproc.worker._process_document", _flaky)
    assert process_one(settings, store, first) == "transient"
    assert store.get("doc-once") is None

    second = _enqueue(settings, "doc-once", body, sha)
    assert process_one(settings, store, second) == "processed"
    s3 = boto3.client("s3", region_name=settings.aws_region)
    listed = s3.list_objects_v2(Bucket=settings.document_bucket, Prefix="processed/doc-once")
    assert listed["KeyCount"] == 1


def test_permanent_failure_releases_claim(settings: Settings, store: IdempotencyStore) -> None:
    sha = "0" * 64
    message = QueueMessage(
        document_id="missing",
        s3_key="incoming/missing",
        sha256=sha,
        submitted_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
    )
    aws.send_message(settings, message.model_dump_json(), content_sha256=sha)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    sqs_message = sqs.receive_message(
        QueueUrl=settings.queue_url, MaxNumberOfMessages=1, AttributeNames=["All"]
    )["Messages"][0]
    assert process_one(settings, store, sqs_message) == "permanent"
    assert store.get("missing") is None


def test_backoff_is_bounded() -> None:
    for count in range(1, 20):
        value = backoff_seconds(count, cap=30)
        assert 1 <= value <= 30


def test_parse_message_rejects_garbage() -> None:
    with pytest.raises(PermanentError):
        _parse_message("not-json")


def test_sha256_mismatch_is_permanent(settings: Settings) -> None:
    aws.put_object_bytes(settings, key="incoming/bad", body=b"aaa", content_type="text/plain")
    msg = _message("bad", "0" * 64)
    with pytest.raises(PermanentError, match="sha256"):
        _process_document(settings, msg)


def test_injected_failure_rate(settings: Settings) -> None:
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
    aws.send_message(settings, _message("inflight", sha).model_dump_json(), content_sha256=sha)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    sqs_message = sqs.receive_message(
        QueueUrl=settings.queue_url, MaxNumberOfMessages=1, AttributeNames=["All"]
    )["Messages"][0]
    assert process_one(settings, store, sqs_message) == "in_progress"


def test_non_transient_client_error(
    settings: Settings, store: IdempotencyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"loan"
    sha = hashlib.sha256(body).hexdigest()
    aws.put_object_bytes(settings, key="incoming/denied", body=body, content_type="application/pdf")
    aws.send_message(settings, _message("denied", sha).model_dump_json(), content_sha256=sha)
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

    monkeypatch.setattr("docproc.worker._process_document", _boom)
    assert process_one(settings, store, sqs_message) == "permanent"
    assert store.get("denied") is None


def test_worker_stops_when_event_set(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()

    class FakeSqs:
        def receive_message(self, **_kwargs: Any) -> dict[str, Any]:
            stop.set()
            return {"Messages": []}

    monkeypatch.setattr(aws, "sqs_client", lambda _s: FakeSqs())
    worker = Worker(settings, store=IdempotencyStore(settings), stop=stop)
    worker.run()
    assert stop.is_set()


def test_run_loop_invokes_worker(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {}

    class FakeWorker:
        def __init__(self, _settings: Settings) -> None:
            pass

        def request_stop(self, signum: int = 0) -> None:
            called["stop"] = True

        def run(self) -> None:
            called["run"] = True

    monkeypatch.setattr("docproc.worker.Worker", FakeWorker)
    monkeypatch.setattr("docproc.worker.signal.signal", lambda *_a: None)
    run_loop(settings)
    assert called.get("run") is True


def test_draining_stop_skips_remaining(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()

    class FakeSqs:
        def receive_message(self, **_kwargs: Any) -> dict[str, Any]:
            stop.set()
            return {
                "Messages": [
                    {
                        "ReceiptHandle": "r",
                        "Body": "not-json",
                        "Attributes": {"ApproximateReceiveCount": "1"},
                    }
                ]
            }

    monkeypatch.setattr(aws, "sqs_client", lambda _s: FakeSqs())
    Worker(settings, store=IdempotencyStore(settings), stop=stop).run()
    assert stop.is_set()


def test_processing_delay(settings: Settings) -> None:
    delayed = settings.model_copy(update={"processing_delay_seconds": 0.01})
    aws.put_object_bytes(delayed, key="incoming/d", body=b"aaa", content_type="text/plain")
    sha = hashlib.sha256(b"aaa").hexdigest()
    _process_document(delayed, _message("d", sha))


def test_request_stop_sets_event(settings: Settings) -> None:
    stop = threading.Event()
    worker = Worker(settings, store=IdempotencyStore(settings), stop=stop)
    worker.request_stop(15)
    assert stop.is_set()


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
    configure_logging("DEBUG")
    formatter = JsonFormatter()
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), None)
    try:
        raise ValueError("x")
    except ValueError:
        record.exc_info = sys.exc_info()
    text = formatter.format(record)
    assert "exc_info" in text
    extra = log_extra(a=1, duration_ms=2.5, error_type="transient")
    assert extra["extra_fields"]["a"] == 1
    assert extra["duration_ms"] == 2.5
    assert extra["error_type"] == "transient"

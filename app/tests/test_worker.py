from __future__ import annotations

import hashlib
import json

import boto3
import pytest

from docproc import aws
from docproc.config import Settings
from docproc.idempotency import IdempotencyStore
from docproc.models import QueueMessage
from docproc.worker import TransientError, backoff_seconds, process_one


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
    aws.send_message(settings, message.model_dump_json(), idempotency_key=sha256)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    received = sqs.receive_message(
        QueueUrl=settings.queue_url,
        MaxNumberOfMessages=1,
        AttributeNames=["All"],
    )
    return received["Messages"][0]  # type: ignore[no-any-return]


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
        idempotency_key=sha,
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


def test_permanent_missing_object(settings: Settings, store: IdempotencyStore) -> None:
    sha = "0" * 64
    message = QueueMessage(
        document_id="missing",
        s3_key="incoming/missing",
        sha256=sha,
        submitted_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
    )
    aws.send_message(settings, message.model_dump_json(), idempotency_key=sha)
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    sqs_message = sqs.receive_message(
        QueueUrl=settings.queue_url, MaxNumberOfMessages=1, AttributeNames=["All"]
    )["Messages"][0]
    assert process_one(settings, store, sqs_message) == "permanent"


def test_backoff_is_bounded() -> None:
    for count in range(1, 20):
        value = backoff_seconds(count, cap=30)
        assert 1 <= value <= 30

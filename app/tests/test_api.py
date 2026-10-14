from __future__ import annotations

import json

import boto3
import pytest
from fastapi.testclient import TestClient

from docproc.config import Settings
from docproc.main import create_app


def test_root_returns_version(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "docproc"
    assert body["version"] == "test"
    assert "X-Request-ID" in response.headers


def test_health_is_live_without_aws(standalone_client: TestClient) -> None:
    response = standalone_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_disabled_without_bucket(standalone_client: TestClient) -> None:
    response = standalone_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


def test_ready_ok_with_moto(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["s3"] == "ok"
    assert body["checks"]["sqs"] == "ok"


def test_ready_503_when_bucket_missing(settings: Settings) -> None:
    broken = settings.model_copy(update={"document_bucket": "does-not-exist"})
    app = create_app(broken)
    with TestClient(app) as client:
        response = client.get("/ready")
        cached = client.get("/ready")
    assert response.status_code == 503
    assert cached.status_code == 503
    assert response.json()["status"] == "degraded"


def test_post_document_enqueues(client: TestClient, settings: Settings) -> None:
    payload = b"%PDF-1.4 test document"
    response = client.post(
        "/documents",
        files={"file": ("loan.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    document_id = body["document_id"]

    s3 = boto3.client("s3", region_name=settings.aws_region)
    obj = s3.get_object(Bucket=settings.document_bucket, Key=f"incoming/{document_id}")
    assert obj["Body"].read() == payload

    sqs = boto3.client("sqs", region_name=settings.aws_region)
    messages = sqs.receive_message(QueueUrl=settings.queue_url, MaxNumberOfMessages=1)
    assert "Messages" in messages
    msg = json.loads(messages["Messages"][0]["Body"])
    assert msg["document_id"] == document_id
    assert msg["sha256"] == body["sha256"]


def test_post_oversize_returns_413(client: TestClient) -> None:
    payload = b"x" * 2048
    response = client.post(
        "/documents",
        files={"file": ("big.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 413


def test_post_unsupported_type_returns_415(client: TestClient) -> None:
    response = client.post(
        "/documents",
        files={"file": ("note.exe", b"MZ", "application/x-msdownload")},
    )
    assert response.status_code == 415


def test_post_without_aws_returns_503(standalone_client: TestClient) -> None:
    response = standalone_client.post(
        "/documents",
        files={"file": ("loan.pdf", b"data", "application/pdf")},
    )
    assert response.status_code == 503


def test_post_empty_file_returns_400(client: TestClient) -> None:
    response = client.post(
        "/documents",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_idempotency_key_is_stable(client: TestClient) -> None:
    payload = b"%PDF-1.4 same"
    first = client.post(
        "/documents",
        files={"file": ("loan.pdf", payload, "application/pdf")},
        headers={"Idempotency-Key": "client-retry-1"},
    )
    second = client.post(
        "/documents",
        files={"file": ("loan.pdf", payload, "application/pdf")},
        headers={"Idempotency-Key": "client-retry-1"},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["document_id"] == second.json()["document_id"]


def test_ingest_non_transient_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    from docproc import aws as aws_mod

    def _boom(*_a: object, **_k: object) -> None:
        raise ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "no"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )

    monkeypatch.setattr(aws_mod, "put_object_bytes", _boom)
    response = client.post(
        "/documents",
        files={"file": ("loan.pdf", b"data", "application/pdf")},
    )
    assert response.status_code == 502


def test_unhandled_error_resets_request_id(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("x")

    with TestClient(app, raise_server_exceptions=True) as test_client:
        with pytest.raises(RuntimeError):
            test_client.get("/boom")


def test_ingest_transient_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from botocore.exceptions import ClientError

    from docproc import aws as aws_mod

    def _boom(*_a: object, **_k: object) -> None:
        raise ClientError(
            {
                "Error": {"Code": "SlowDown", "Message": "slow"},
                "ResponseMetadata": {"HTTPStatusCode": 503},
            },
            "PutObject",
        )

    monkeypatch.setattr(aws_mod, "put_object_bytes", _boom)
    response = client.post(
        "/documents",
        files={"file": ("loan.pdf", b"data", "application/pdf")},
    )
    assert response.status_code == 503

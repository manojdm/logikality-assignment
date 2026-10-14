"""Shared fixtures: moto-backed S3, SQS, DynamoDB and a FastAPI test client."""

from __future__ import annotations

import os
from collections.abc import Iterator

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from docproc.aws import clear_client_cache
from docproc.config import Settings, get_settings
from docproc.idempotency import IdempotencyStore
from docproc.main import create_app

BUCKET = "logikality-documents"
QUEUE_NAME = "logikality-processing"
TABLE = "logikality-idempotency"
REGION = "us-east-1"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_REGION", REGION)
    get_settings.cache_clear()
    clear_client_cache()


@pytest.fixture
def aws_backend() -> Iterator[dict[str, str]]:
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
        dynamodb = boto3.client("dynamodb", region_name=REGION)
        dynamodb.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.get_waiter("table_exists").wait(TableName=TABLE)
        yield {"bucket": BUCKET, "queue_url": queue_url, "table": TABLE}


@pytest.fixture
def settings(aws_backend: dict[str, str]) -> Settings:
    get_settings.cache_clear()
    clear_client_cache()
    return Settings(
        app_env="test",
        aws_region=REGION,
        document_bucket=aws_backend["bucket"],
        queue_url=aws_backend["queue_url"],
        idempotency_table=aws_backend["table"],
        app_version="test",
        max_upload_bytes=1024,
        aws_endpoint_url=None,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def store(settings: Settings) -> IdempotencyStore:
    return IdempotencyStore(settings)


@pytest.fixture
def standalone_client() -> Iterator[TestClient]:
    """Container-style run with AWS resources unset."""
    get_settings.cache_clear()
    clear_client_cache()
    standalone = Settings(app_env="test", app_version="test", document_bucket="", queue_url="")
    app = create_app(standalone)
    with TestClient(app) as test_client:
        yield test_client


# Keep os imported so tests can patch env if needed.
assert os.environ.get("AWS_DEFAULT_REGION") or True

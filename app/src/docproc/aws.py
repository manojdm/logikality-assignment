"""Thin boto3 client factory that honours LocalStack via AWS_ENDPOINT_URL."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from docproc.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient
else:
    DynamoDBServiceResource = Any
    S3Client = Any
    SQSClient = Any

_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=3,
    read_timeout=5,
)

_PROBE_CONFIG = Config(
    retries={"max_attempts": 1, "mode": "standard"},
    connect_timeout=1,
    read_timeout=1,
)


def _client_kwargs(settings: Settings, config: Config = _RETRY_CONFIG) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "config": config,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return kwargs


@lru_cache(maxsize=8)
def s3_client(settings: Settings) -> S3Client:
    return boto3.client("s3", **_client_kwargs(settings))


@lru_cache(maxsize=8)
def sqs_client(settings: Settings) -> SQSClient:
    return boto3.client("sqs", **_client_kwargs(settings))


@lru_cache(maxsize=8)
def dynamodb_resource(settings: Settings) -> DynamoDBServiceResource:
    kwargs = _client_kwargs(settings)
    return boto3.resource("dynamodb", **kwargs)


def clear_client_cache() -> None:
    s3_client.cache_clear()
    sqs_client.cache_clear()
    dynamodb_resource.cache_clear()


def put_object_bytes(
    settings: Settings,
    *,
    key: str,
    body: bytes,
    content_type: str,
    metadata: dict[str, str] | None = None,
) -> None:
    extra: dict[str, Any] = {
        "Bucket": settings.document_bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
        "Metadata": metadata or {},
    }
    if settings.kms_key_id:
        extra["ServerSideEncryption"] = "aws:kms"
        extra["SSEKMSKeyId"] = settings.kms_key_id
    s3_client(settings).put_object(**extra)


def get_object_bytes(settings: Settings, key: str) -> bytes:
    response = s3_client(settings).get_object(Bucket=settings.document_bucket, Key=key)
    return bytes(response["Body"].read())


def head_bucket(settings: Settings) -> None:
    s3_client(settings).head_bucket(Bucket=settings.document_bucket)


def probe_head_bucket(settings: Settings) -> None:
    boto3.client("s3", **_client_kwargs(settings, _PROBE_CONFIG)).head_bucket(
        Bucket=settings.document_bucket
    )


def probe_queue_attributes(settings: Settings) -> dict[str, str]:
    response = boto3.client("sqs", **_client_kwargs(settings, _PROBE_CONFIG)).get_queue_attributes(
        QueueUrl=settings.queue_url, AttributeNames=["QueueArn"]
    )
    raw = response.get("Attributes") or {}
    return {str(key): str(value) for key, value in raw.items()}


def object_exists(settings: Settings, key: str) -> bool:
    try:
        s3_client(settings).head_object(Bucket=settings.document_bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def send_message(settings: Settings, body: str, content_sha256: str) -> str:
    response = sqs_client(settings).send_message(
        QueueUrl=settings.queue_url,
        MessageBody=body,
        MessageAttributes={"content_sha256": {"StringValue": content_sha256, "DataType": "String"}},
    )
    return str(response["MessageId"])


def get_queue_attributes(settings: Settings) -> dict[str, str]:
    response = sqs_client(settings).get_queue_attributes(
        QueueUrl=settings.queue_url, AttributeNames=["All"]
    )
    raw = response.get("Attributes") or {}
    return {str(key): str(value) for key, value in raw.items()}


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, BotoCoreError):
        return True
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        http = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        if code in {
            "Throttling",
            "ThrottlingException",
            "ProvisionedThroughputExceededException",
            "RequestTimeout",
            "ServiceUnavailable",
            "InternalError",
            "SlowDown",
        }:
            return True
        if http >= 500:
            return True
    return False

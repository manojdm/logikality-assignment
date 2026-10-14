from __future__ import annotations

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from docproc import aws
from docproc.config import Settings, get_settings


def _client_error(code: str, http: int = 400) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": http}},
        "Op",
    )


def test_put_object_with_kms(settings: Settings) -> None:
    kms_settings = settings.model_copy(update={"kms_key_id": "alias/test"})
    aws.put_object_bytes(kms_settings, key="incoming/k", body=b"x", content_type="text/plain")
    assert aws.object_exists(kms_settings, "incoming/k")
    assert not aws.object_exists(kms_settings, "incoming/missing")
    assert aws.get_object_bytes(kms_settings, "incoming/k") == b"x"


def test_empty_endpoint_and_kms_validators() -> None:
    get_settings.cache_clear()
    parsed = Settings(aws_endpoint_url="", kms_key_id="")
    assert parsed.aws_endpoint_url is None
    assert parsed.kms_key_id is None


def test_is_transient_classification() -> None:
    assert aws.is_transient(_client_error("Throttling"))
    assert aws.is_transient(_client_error("InternalError", http=500))
    assert not aws.is_transient(_client_error("AccessDenied"))
    assert aws.is_transient(BotoCoreError())


def test_head_bucket_and_probes(settings: Settings) -> None:
    aws.head_bucket(settings)
    aws.probe_head_bucket(settings)
    attrs = aws.probe_queue_attributes(settings)
    assert "QueueArn" in attrs or attrs == attrs


def test_object_exists_reraises_other_errors(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    err = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "no"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "HeadObject",
    )

    def _boom(*_a: object, **_k: object) -> object:
        raise err

    monkeypatch.setattr(aws.s3_client(settings), "head_object", _boom)
    with pytest.raises(ClientError):
        aws.object_exists(settings, "incoming/x")


def test_endpoint_url_passed(settings: Settings) -> None:
    local = settings.model_copy(update={"aws_endpoint_url": "http://localhost:4566"})
    kwargs = aws._client_kwargs(local)
    assert kwargs["endpoint_url"] == "http://localhost:4566"

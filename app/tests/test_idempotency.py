from __future__ import annotations

import time

import pytest

from docproc.config import Settings
from docproc.idempotency import ClaimResult, IdempotencyStore


def test_first_claim_wins(store: IdempotencyStore) -> None:
    assert store.claim("doc-a") is ClaimResult.CLAIMED
    assert store.claim("doc-a") is ClaimResult.IN_PROGRESS


def test_completed_claim_is_already_completed(store: IdempotencyStore) -> None:
    assert store.claim("doc-b") is ClaimResult.CLAIMED
    store.complete("doc-b")
    assert store.claim("doc-b") is ClaimResult.ALREADY_COMPLETED
    item = store.get("doc-b")
    assert item is not None
    assert item["status"] == "COMPLETED"


def test_independent_documents(store: IdempotencyStore, settings: Settings) -> None:
    assert settings.idempotency_table
    assert store.claim("doc-1") is ClaimResult.CLAIMED
    assert store.claim("doc-2") is ClaimResult.CLAIMED


def test_release_allows_reclaim(store: IdempotencyStore) -> None:
    assert store.claim("doc-rel") is ClaimResult.CLAIMED
    store.release("doc-rel")
    assert store.get("doc-rel") is None
    assert store.claim("doc-rel") is ClaimResult.CLAIMED


def test_release_does_not_delete_completed(store: IdempotencyStore) -> None:
    assert store.claim("doc-keep") is ClaimResult.CLAIMED
    store.complete("doc-keep")
    store.release("doc-keep")
    item = store.get("doc-keep")
    assert item is not None
    assert item["status"] == "COMPLETED"


def test_release_reraises_other_errors(
    store: IdempotencyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    err = ClientError(
        {
            "Error": {"Code": "InternalServerError", "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        },
        "DeleteItem",
    )

    def _boom(**_k: object) -> None:
        raise err

    monkeypatch.setattr(store._table, "delete_item", _boom)
    with pytest.raises(ClientError):
        store.release("x")


def test_expired_lease_can_be_reclaimed(store: IdempotencyStore) -> None:
    assert store.claim("doc-lease") is ClaimResult.CLAIMED
    store._table.update_item(
        Key={"pk": "doc-lease"},
        UpdateExpression="SET lease_expires_at = :past",
        ExpressionAttributeValues={":past": int(time.time()) - 10},
    )
    assert store.claim("doc-lease") is ClaimResult.CLAIMED

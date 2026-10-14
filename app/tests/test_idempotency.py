from __future__ import annotations

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

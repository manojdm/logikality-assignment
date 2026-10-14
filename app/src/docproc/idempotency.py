"""DynamoDB-backed idempotency claims for at-least-once SQS delivery."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from botocore.exceptions import ClientError

from docproc.aws import dynamodb_resource
from docproc.config import Settings


class ClaimResult(StrEnum):
    CLAIMED = "claimed"
    ALREADY_COMPLETED = "already_completed"
    IN_PROGRESS = "in_progress"


class IdempotencyStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._table = dynamodb_resource(settings).Table(settings.idempotency_table)

    def claim(self, document_id: str) -> ClaimResult:
        """Conditional PutItem: first writer owns the document.

        Returns ALREADY_COMPLETED when a prior worker finished so the duplicate
        SQS message can be deleted. Returns IN_PROGRESS when another worker
        still holds the claim (do not delete the message).
        """
        now = int(time.time())
        item: dict[str, Any] = {
            "pk": document_id,
            "status": "IN_PROGRESS",
            "claimed_at": now,
            "expires_at": now + self._settings.idempotency_ttl_seconds,
        }
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
            return ClaimResult.CLAIMED
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self._table.get_item(Key={"pk": document_id}).get("Item") or {}
            status = str(existing.get("status", ""))
            if status == "COMPLETED":
                return ClaimResult.ALREADY_COMPLETED
            return ClaimResult.IN_PROGRESS

    def complete(self, document_id: str) -> None:
        now = int(time.time())
        self._table.update_item(
            Key={"pk": document_id},
            UpdateExpression="SET #s = :s, completed_at = :c, expires_at = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "COMPLETED",
                ":c": now,
                ":e": now + self._settings.idempotency_ttl_seconds,
            },
        )

    def get(self, document_id: str) -> dict[str, Any] | None:
        item = self._table.get_item(Key={"pk": document_id}).get("Item")
        return dict(item) if item else None

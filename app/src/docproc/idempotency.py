"""DynamoDB-backed idempotency claims with a reclaimable lease.

A claim is a lease, not a permanent lock. If the worker crashes or returns a
transient/permanent error it either expires (lease_expires_at) or is released
explicitly, so a redelivery can proceed. COMPLETED records are never overwritten.
"""

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
        """Take or reclaim a lease.

        Succeeds when the item is missing, or when it is still IN_PROGRESS and
        the lease has expired. COMPLETED items stay COMPLETED.
        """
        now = int(time.time())
        lease = now + self._settings.visibility_timeout_seconds
        item: dict[str, Any] = {
            "pk": document_id,
            "status": "IN_PROGRESS",
            "claimed_at": now,
            "lease_expires_at": lease,
            "expires_at": now + self._settings.idempotency_ttl_seconds,
        }
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=(
                    "attribute_not_exists(pk) OR (#s = :in_progress AND lease_expires_at < :now)"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":in_progress": "IN_PROGRESS", ":now": now},
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

    def release(self, document_id: str) -> None:
        """Drop an IN_PROGRESS claim so a retry can take a new lease.

        No-op if another worker already completed or reclaimed the item.
        """
        try:
            self._table.delete_item(
                Key={"pk": document_id},
                ConditionExpression="#s = :in_progress",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":in_progress": "IN_PROGRESS"},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    def get(self, document_id: str) -> dict[str, Any] | None:
        item = self._table.get_item(Key={"pk": document_id}).get("Item")
        return dict(item) if item else None

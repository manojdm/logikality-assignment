"""Structured JSON logging with request/document context."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
document_id_var: ContextVar[str | None] = ContextVar("document_id", default=None)
receive_count_var: ContextVar[int | None] = ContextVar("receive_count", default=None)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for CloudWatch Logs Insights."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        request_id = request_id_var.get()
        document_id = document_id_var.get()
        receive_count = receive_count_var.get()
        if request_id:
            payload["request_id"] = request_id
        if document_id:
            payload["document_id"] = document_id
        if receive_count is not None:
            payload["receive_count"] = receive_count
        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        error_type = getattr(record, "error_type", None)
        if error_type:
            payload["error_type"] = error_type
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def log_extra(**fields: Any) -> dict[str, Any]:
    return {"extra": {"extra_fields": fields}}

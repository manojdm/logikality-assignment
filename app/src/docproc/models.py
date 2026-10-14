"""Pydantic models shared by the API and worker."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    service: str = "docproc"
    version: str
    message: str = "Logikality document service"


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "degraded", "disabled"]
    checks: dict[str, str] = Field(default_factory=dict)


class DocumentAccepted(BaseModel):
    document_id: str
    s3_key: str
    sha256: str
    status: Literal["accepted"] = "accepted"


class QueueMessage(BaseModel):
    document_id: str
    s3_key: str
    sha256: str
    submitted_at: datetime
    content_type: str = "application/octet-stream"

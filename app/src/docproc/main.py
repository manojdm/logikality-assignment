"""HTTP API: liveness, readiness, and document ingest."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4, uuid5

from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from docproc import aws
from docproc.config import Settings, get_settings
from docproc.logging import configure_logging, log_extra, request_id_var
from docproc.models import (
    DocumentAccepted,
    HealthResponse,
    QueueMessage,
    ReadyResponse,
    RootResponse,
)

ALLOWED_CONTENT_TYPES: Final[set[str]] = {
    "application/pdf",
    "application/octet-stream",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "text/plain",
}

DOCUMENT_NAMESPACE: Final[UUID] = uuid5(uuid.NAMESPACE_URL, "https://logikality.example/docproc")
READY_CACHE_TTL_SECONDS: Final[float] = 5.0

logger = logging.getLogger("docproc.api")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id") or str(uuid4())
        token = request_id_var.set(incoming)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers["X-Request-ID"] = incoming
            logger.info(
                "request_complete",
                extra=log_extra(
                    duration_ms=duration_ms,
                    path=request.url.path,
                    method=request.method,
                    status=response.status_code,
                ),
            )
            return response
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "unhandled_error",
                extra=log_extra(duration_ms=duration_ms, path=request.url.path),
            )
            raise
        finally:
            request_id_var.reset(token)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    ready_cache: dict[str, tuple[float, ReadyResponse, int]] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("startup", extra=log_extra(version=settings.app_version))
        yield
        aws.clear_client_cache()
        logger.info("shutdown")

    app = FastAPI(
        title="Logikality document service",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)

    @app.get("/", response_model=RootResponse)
    def root() -> RootResponse:
        return RootResponse(version=settings.app_version)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness: no downstream calls, so a queue/S3 outage cannot restart-loop the process."""
        return HealthResponse()

    @app.get("/ready", response_model=ReadyResponse)
    def ready(response: Response) -> ReadyResponse:
        """Readiness: cheap S3/SQS probes, cached 5s. Disabled when DOCUMENT_BUCKET is unset."""
        if not settings.aws_configured:
            return ReadyResponse(status="disabled", checks={"aws": "disabled"})
        cached = ready_cache.get("ready")
        now = time.monotonic()
        if cached and now - cached[0] < READY_CACHE_TTL_SECONDS:
            payload, status_code = cached[1], cached[2]
            response.status_code = status_code
            return payload
        checks: dict[str, str] = {}
        ok = True
        try:
            aws.probe_head_bucket(settings)
            checks["s3"] = "ok"
        except Exception as exc:  # noqa: BLE001 — surface any probe failure as not-ready
            ok = False
            checks["s3"] = f"error:{type(exc).__name__}"
            logger.warning("ready_s3_failed", extra=log_extra(error=str(exc)))
        try:
            aws.probe_queue_attributes(settings)
            checks["sqs"] = "ok"
        except Exception as exc:  # noqa: BLE001
            ok = False
            checks["sqs"] = f"error:{type(exc).__name__}"
            logger.warning("ready_sqs_failed", extra=log_extra(error=str(exc)))
        if not ok:
            payload = ReadyResponse(status="degraded", checks=checks)
            response.status_code = 503
            ready_cache["ready"] = (now, payload, 503)
            return payload
        payload = ReadyResponse(status="ok", checks=checks)
        ready_cache["ready"] = (now, payload, 200)
        return payload

    @app.post("/documents", response_model=DocumentAccepted, status_code=202)
    async def ingest(
        request: Request,
        file: UploadFile = File(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> DocumentAccepted:
        content_type = file.content_type or "application/octet-stream"
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail=f"unsupported content type: {content_type}")
        if not settings.aws_configured:
            raise HTTPException(status_code=503, detail="document storage is not configured")

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.max_upload_bytes + 4096:
                    # +4 KiB slack for multipart framing around the file body.
                    raise HTTPException(status_code=413, detail="payload too large")
            except ValueError:
                pass

        body = await file.read(settings.max_upload_bytes + 1)
        if len(body) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="payload too large")
        if not body:
            raise HTTPException(status_code=400, detail="empty file")

        document_id = (
            str(uuid5(DOCUMENT_NAMESPACE, idempotency_key)) if idempotency_key else str(uuid4())
        )
        sha256 = hashlib.sha256(body).hexdigest()
        s3_key = f"incoming/{document_id}"
        submitted_at = datetime.now(UTC)
        message = QueueMessage(
            document_id=document_id,
            s3_key=s3_key,
            sha256=sha256,
            submitted_at=submitted_at,
            content_type=content_type,
        )
        try:
            aws.put_object_bytes(
                settings,
                key=s3_key,
                body=body,
                content_type=content_type,
                metadata={"sha256": sha256, "document-id": document_id},
            )
            aws.send_message(settings, message.model_dump_json(), content_sha256=sha256)
        except Exception as exc:
            if aws.is_transient(exc):
                logger.warning("ingest_transient", extra=log_extra(error=str(exc)))
                raise HTTPException(status_code=503, detail="upstream unavailable") from exc
            logger.exception("ingest_failed")
            raise HTTPException(status_code=502, detail="failed to persist document") from exc
        logger.info("document_accepted", extra=log_extra(document_id=document_id, sha256=sha256))
        return DocumentAccepted(document_id=document_id, s3_key=s3_key, sha256=sha256)

    return app


app = create_app()

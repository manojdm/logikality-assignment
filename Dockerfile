# python:3.12-slim should be digest-pinned in production.
# Dependabot (docker ecosystem at /) is configured to bump this tag.
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY app/requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.14-slim AS runtime

# OCI labels populated at build time. revision is the git SHA.
ARG GIT_SHA=dev
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.source="https://github.com/logikality/docproc" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.title="logikality-docproc"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    APP_VERSION="${GIT_SHA}" \
    GIT_SHA="${GIT_SHA}"

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /app app

COPY --from=builder /opt/venv /opt/venv
COPY app/src /app/src

WORKDIR /app
USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

CMD ["uvicorn", "docproc.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]

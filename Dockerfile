# python:3.12-slim@sha256:a6e34c59... (bookworm) — digest-pinned so rebuilds are reproducible.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY app/requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

ARG GIT_SHA=dev
ARG BUILD_DATE=unknown
ARG IMAGE_SOURCE=https://github.com/example/logikality
LABEL org.opencontainers.image.source="${IMAGE_SOURCE}" \
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

# Drop pip/setuptools so Trivy does not report HIGH findings from pip's vendored copies.
# hadolint ignore=DL3013
RUN /opt/venv/bin/python -m pip uninstall -y pip setuptools \
    && python -m pip uninstall -y pip setuptools || true

WORKDIR /app
USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

CMD ["uvicorn", "docproc.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--no-access-log"]

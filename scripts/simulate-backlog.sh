#!/usr/bin/env bash
# Deterministic LocalStack demo: two poison messages go to the DLQ while a
# slow, 30%-flaky worker drains a real backlog.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:${PATH}"
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
ENDPOINT="${AWS_ENDPOINT_URL:-http://localhost:4566}"
API="${API_URL:-http://127.0.0.1:18080}"
PY="${ROOT}/app/.venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY="python3"
fi

cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> starting stack with slow, flaky worker and maxReceiveCount=3"
MAX_RECEIVE_COUNT=3 PROCESSING_DELAY_SECONDS=1 FAILURE_RATE=0.3 docker compose up -d --build

echo "==> waiting for API"
for _ in $(seq 1 60); do
  curl -fsS "${API}/health" >/dev/null 2>&1 && break
  sleep 2
done

QUEUE_URL="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-url --queue-name logikality-processing --query QueueUrl --output text)"
DLQ_URL="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-url --queue-name logikality-processing-dlq --query QueueUrl --output text)"

echo "==> DLQ depth before poisons"
aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
  --queue-url "${DLQ_URL}" \
  --attribute-names ApproximateNumberOfMessages \
  --output text --query 'Attributes.ApproximateNumberOfMessages'

echo "==> injecting poison: invalid body"
aws --endpoint-url "${ENDPOINT}" sqs send-message \
  --queue-url "${QUEUE_URL}" \
  --message-body 'this-is-not-json' >/dev/null

echo "==> injecting poison: missing object"
MISSING="$("${PY}" -c "import json; from datetime import datetime, timezone; print(json.dumps({'document_id': 'missing-object', 's3_key': 'incoming/does-not-exist', 'sha256': '0'*64, 'submitted_at': datetime.now(timezone.utc).isoformat(), 'content_type': 'text/plain'}))")"
aws --endpoint-url "${ENDPOINT}" sqs send-message \
  --queue-url "${QUEUE_URL}" \
  --message-body "${MISSING}" >/dev/null

echo "==> submitting a burst of valid documents"
for i in $(seq 1 6); do
  echo "burst-${i}" > /tmp/logikality-doc.txt
  curl -fsS -X POST "${API}/documents" -F "file=@/tmp/logikality-doc.txt;type=text/plain" >/dev/null
  echo "submitted ${i}"
done

echo "==> sampling until DLQ=2 and processing queue drains"
DLQ_HIT=0
DRAINED=0
for _ in $(seq 1 24); do
  echo "--- $(date -u +%H:%M:%S) ---"
  VISIBLE="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
    --queue-url "${QUEUE_URL}" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.{v:ApproximateNumberOfMessages,n:ApproximateNumberOfMessagesNotVisible}' \
    --output text)"
  DLQ="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
    --queue-url "${DLQ_URL}" \
    --attribute-names ApproximateNumberOfMessages \
    --query 'Attributes.ApproximateNumberOfMessages' --output text)"
  echo "processing=${VISIBLE} dlq=${DLQ}"
  if [[ "${DLQ}" == "2" ]]; then
    DLQ_HIT=1
  fi
  if [[ "${VISIBLE}" == "0"$'\t'"0" || "${VISIBLE}" == "0 0" ]]; then
    DRAINED=1
  fi
  if [[ "${DLQ_HIT}" -eq 1 && "${DRAINED}" -eq 1 ]]; then
    break
  fi
  sleep 5
done

echo "==> final depths"
echo "processing queue:"
aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
  --queue-url "${QUEUE_URL}" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --output table
echo "DLQ:"
aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
  --queue-url "${DLQ_URL}" \
  --attribute-names ApproximateNumberOfMessages \
  --output table

if [[ "${DLQ_HIT}" -ne 1 ]]; then
  echo "FAIL: expected DLQ to reach 2 (invalid body + missing object)"
  exit 1
fi
echo "backlog simulation complete: DLQ filled with 2 poison messages"

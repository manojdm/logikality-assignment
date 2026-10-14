#!/usr/bin/env bash
# Demonstrates a growing SQS backlog, retries, and DLQ redrive locally.
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

cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> starting stack with slow, flaky worker"
PROCESSING_DELAY_SECONDS=5 FAILURE_RATE=0.3 docker compose up -d --build

echo "==> waiting for API"
for _ in $(seq 1 60); do
  curl -fsS "${API}/health" >/dev/null 2>&1 && break
  sleep 2
done

echo "==> submitting a burst of documents"
for i in $(seq 1 8); do
  echo "burst-${i}" > /tmp/logikality-doc.txt
  curl -fsS -X POST "${API}/documents" -F "file=@/tmp/logikality-doc.txt;type=text/plain" >/dev/null
  echo "submitted ${i}"
done

QUEUE_URL="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-url --queue-name logikality-processing --query QueueUrl --output text)"
DLQ_URL="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-url --queue-name logikality-processing-dlq --query QueueUrl --output text)"

echo "==> sampling queue attributes for 40s"
for _ in $(seq 1 8); do
  echo "--- $(date -u +%H:%M:%S) ---"
  echo "processing queue:"
  aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
    --queue-url "${QUEUE_URL}" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --output table || true
  echo "DLQ:"
  aws --endpoint-url "${ENDPOINT}" sqs get-queue-attributes \
    --queue-url "${DLQ_URL}" \
    --attribute-names ApproximateNumberOfMessages \
    --output table || true
  sleep 5
done

echo "==> backlog simulation complete (see ApproximateNumberOfMessages and DLQ depth above)"

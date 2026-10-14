#!/usr/bin/env bash
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
BUCKET="${DOCUMENT_BUCKET:-logikality-documents}"
QUEUE_NAME="${QUEUE_NAME:-logikality-processing}"
PY="${ROOT}/app/.venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY="python3"
fi

cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> bringing up compose stack"
docker compose up -d --build

echo "==> waiting for /ready"
READY=0
for _ in $(seq 1 60); do
  if curl -fsS "${API}/ready" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
if [[ "${READY}" -ne 1 ]]; then
  echo "FAIL: /ready never succeeded"
  docker compose logs --tail=80
  exit 1
fi
curl -fsS "${API}/ready"
echo

echo "==> posting a document"
DOC_JSON="$(curl -fsS -X POST "${API}/documents" \
  -F "file=@${ROOT}/scripts/e2e.sh;type=text/plain")"
echo "${DOC_JSON}"
DOCUMENT_ID="$("${PY}" -c "import json,sys; print(json.loads(sys.argv[1])['document_id'])" "${DOC_JSON}")"
SHA256="$("${PY}" -c "import json,sys; print(json.loads(sys.argv[1])['sha256'])" "${DOC_JSON}")"
echo "document_id=${DOCUMENT_ID}"

echo "==> waiting for processed object"
PROCESSED="processed/${DOCUMENT_ID}.json"
FOUND=0
for _ in $(seq 1 30); do
  if aws --endpoint-url "${ENDPOINT}" s3 ls "s3://${BUCKET}/${PROCESSED}" >/dev/null 2>&1; then
    FOUND=1
    break
  fi
  sleep 1
done
if [[ "${FOUND}" -ne 1 ]]; then
  echo "FAIL: processed object never appeared"
  aws --endpoint-url "${ENDPOINT}" s3 ls "s3://${BUCKET}/" --recursive || true
  docker compose logs worker --tail=50 || true
  exit 1
fi
aws --endpoint-url "${ENDPOINT}" s3 cp "s3://${BUCKET}/${PROCESSED}" -

echo "==> replaying the same SQS message (idempotency)"
BODY="$("${PY}" -c "import json,sys; from datetime import datetime, timezone; print(json.dumps({'document_id': sys.argv[1], 's3_key': 'incoming/'+sys.argv[1], 'sha256': sys.argv[2], 'submitted_at': datetime.now(timezone.utc).isoformat(), 'content_type': 'text/plain'}))" "${DOCUMENT_ID}" "${SHA256}")"
QUEUE_URL="$(aws --endpoint-url "${ENDPOINT}" sqs get-queue-url --queue-name "${QUEUE_NAME}" --query QueueUrl --output text)"
aws --endpoint-url "${ENDPOINT}" sqs send-message --queue-url "${QUEUE_URL}" --message-body "${BODY}" >/dev/null
sleep 5
COUNT="$(aws --endpoint-url "${ENDPOINT}" s3 ls "s3://${BUCKET}/processed/" | wc -l | tr -d ' ')"
echo "processed object count=${COUNT}"
if [[ "${COUNT}" -lt 1 ]]; then
  echo "FAIL: expected processed object to remain"
  exit 1
fi

echo "PASS"

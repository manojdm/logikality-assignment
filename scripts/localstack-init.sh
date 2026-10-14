#!/usr/bin/env bash
# Runs inside LocalStack once the emulator is ready.
set -euo pipefail

BUCKET="${BUCKET:-logikality-documents}"
QUEUE="${QUEUE:-logikality-processing}"
DLQ="${DLQ:-logikality-processing-dlq}"
TABLE="${TABLE:-logikality-idempotency}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "initialising localstack resources in ${REGION}"

awslocal s3 mb "s3://${BUCKET}" || true

awslocal sqs create-queue --queue-name "${DLQ}" --region "${REGION}" >/dev/null || true
DLQ_URL="$(awslocal sqs get-queue-url --queue-name "${DLQ}" --query QueueUrl --output text)"
DLQ_ARN="$(awslocal sqs get-queue-attributes --queue-url "${DLQ_URL}" --attribute-names QueueArn --query Attributes.QueueArn --output text)"

ATTRS="$(mktemp)"
cat >"${ATTRS}" <<EOF
{
  "VisibilityTimeout": "60",
  "ReceiveMessageWaitTimeSeconds": "20",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"${DLQ_ARN}\",\"maxReceiveCount\":\"5\"}"
}
EOF
awslocal sqs create-queue \
  --queue-name "${QUEUE}" \
  --attributes "file://${ATTRS}" \
  --region "${REGION}" >/dev/null || true
rm -f "${ATTRS}"

awslocal dynamodb create-table \
  --table-name "${TABLE}" \
  --attribute-definitions AttributeName=pk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "${REGION}" >/dev/null || true

echo "localstack init complete"
awslocal sqs get-queue-url --queue-name "${QUEUE}"
awslocal dynamodb list-tables
awslocal s3 ls

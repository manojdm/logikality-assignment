#!/usr/bin/env bash
# Recreate the demo stack in ap-south-1 and print a public URL.
# Usage: ./scripts/launch.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

export AWS_PROFILE="${AWS_PROFILE:-logikality}"
export AWS_REGION="ap-south-1"
export AWS_DEFAULT_REGION="ap-south-1"

ACCOUNT="978841975306"
TAG="${IMAGE_TAG:-sha-live}"
ECR_HOST="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${ECR_HOST}/logikality-dev-docproc:${TAG}"

echo "==> SSO login (${AWS_PROFILE}, workload region ${AWS_REGION})"
aws sso login --profile "${AWS_PROFILE}"

ACTUAL="$(aws sts get-caller-identity --query Account --output text)"
echo "account ${ACTUAL} region ${AWS_REGION}"
if [[ "${ACTUAL}" != "${ACCOUNT}" ]]; then
  echo "wrong account: ${ACTUAL}, expected ${ACCOUNT}" >&2
  exit 1
fi

cat > infra/terraform.tfvars <<EOF
project_name          = "logikality"
environment           = "dev"
aws_region            = "${AWS_REGION}"
owner                 = "founding-devops"
allowed_account_ids   = ["${ACCOUNT}"]
enable_compute        = true
container_image       = ""
enable_github_oidc    = false
enable_access_logging = true
enable_object_lock    = false
EOF

echo "==> Terraform apply (no ECS tasks yet)"
cd infra
terraform init -backend=false -input=false
terraform apply -auto-approve -input=false \
  -var="aws_region=${AWS_REGION}" \
  -var="container_image="
ECR="$(terraform output -raw ecr_repository_url)"
cd "${ROOT}"

echo "==> Build linux/amd64 image and push ${ECR}:${TAG}"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_HOST}"
docker build --platform linux/amd64 --build-arg GIT_SHA=live \
  -t "logikality-docproc:live" .
docker tag logikality-docproc:live "${ECR}:${TAG}"
docker push "${ECR}:${TAG}"

perl -i -pe "s|container_image\\s*=\\s*\"\"|container_image       = \"${IMAGE_URI}\"|" infra/terraform.tfvars

echo "==> Terraform apply (API + worker)"
cd infra
terraform apply -auto-approve -input=false \
  -var="aws_region=${AWS_REGION}" \
  -var="container_image=${IMAGE_URI}"
URL="$(terraform output -raw api_url)"
cd "${ROOT}"

echo "==> Waiting for /health on ${URL}"
for _ in $(seq 1 36); do
  if curl -fsS --max-time 5 "${URL}/health" >/dev/null; then
    echo
    echo "API:    ${URL}"
    echo "health: $(curl -fsS --max-time 5 "${URL}/health")"
    echo "ready:  $(curl -fsS --max-time 5 "${URL}/ready" || true)"
    echo "root:   $(curl -fsS --max-time 5 "${URL}/")"
    exit 0
  fi
  sleep 10
done

echo "timed out waiting for ${URL}/health" >&2
exit 1

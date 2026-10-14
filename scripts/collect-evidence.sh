#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:${PATH}"
PY="${ROOT}/app/.venv/bin/python"
EV="${ROOT}/docs/evidence"
mkdir -p "${EV}"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
IMAGE="logikality-docproc:local"

redact() {
  # Mask 12-digit account IDs that may appear in plans.
  sed -E 's/[0-9]{12}/************/g'
}

run() {
  local out="$1"; shift
  echo "==> $* (tee ${out})"
  {
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# $*"
    echo
    "$@" 2>&1 || echo "EXIT:$?"
  } | redact | tee "${EV}/${out}"
}

run ruff.txt "${PY}" -m ruff check app
run ruff-format.txt "${PY}" -m ruff format --check app
run mypy.txt "${PY}" -m mypy --strict app/src
{
  echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# pytest"
  (cd "${ROOT}/app" && "${PY}" -m pytest tests --cov=docproc --cov-report=term-missing --cov-fail-under=85)
} 2>&1 | tee "${EV}/pytest.txt"

run hadolint.txt hadolint Dockerfile
run tf-fmt.txt terraform -chdir=infra fmt -check -recursive
run tf-validate.txt bash -c "terraform -chdir=infra init -backend=false -input=false >/dev/null && terraform -chdir=infra validate"
run tf-test.txt terraform -chdir=infra test
run tflint.txt bash -c "tflint --chdir=infra --recursive --init >/dev/null && tflint --chdir=infra --recursive"
if command -v checkov >/dev/null; then
  run checkov.txt checkov -d infra --framework terraform --compact --quiet
elif [[ -x "${ROOT}/.tools/checkov/bin/checkov" ]]; then
  run checkov.txt "${ROOT}/.tools/checkov/bin/checkov" -d infra --framework terraform --compact --quiet
else
  echo "checkov not installed" | tee "${EV}/checkov.txt"
fi
run actionlint.txt actionlint || true

run iam-static.txt bash -c "grep -n 's3:\\*' infra/modules/document-pipeline/iam.tf && exit 1 || echo 'no s3:* in worker/api IAM'; grep -n 'Resource = \"\\*\"' infra/modules/document-pipeline/iam.tf && exit 1 || echo 'no Resource * in IAM statements (KMS policy data uses * on kms key as required)'"

echo "==> docker build"
{
  echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  docker build --build-arg GIT_SHA="${GIT_SHA}" -t "${IMAGE}" -t "logikality-docproc:${GIT_SHA}" .
  docker images "${IMAGE}"
} 2>&1 | tee "${EV}/docker-build.txt"

echo "==> docker run smoke"
docker rm -f logikality-evidence-api >/dev/null 2>&1 || true
{
  docker run -d --name logikality-evidence-api -p 18080:8080 "${IMAGE}"
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:18080/health && break
    sleep 1
  done
  echo
  curl -fsS http://127.0.0.1:18080/
  echo
  curl -fsS http://127.0.0.1:18080/health
  echo
  n=0
  until docker inspect --format '{{.State.Health.Status}}' logikality-evidence-api 2>/dev/null | grep -q healthy; do
    n=$((n+1))
    if [ "$n" -gt 20 ]; then
      echo "timed out waiting for healthy"
      break
    fi
    sleep 2
  done
  docker ps --filter name=logikality-evidence-api --format 'table {{.Names}}\t{{.Status}}'
} 2>&1 | tee "${EV}/docker-run.txt"
docker rm -f logikality-evidence-api >/dev/null 2>&1 || true

echo "==> e2e"
./scripts/e2e.sh 2>&1 | tee "${EV}/e2e.txt" || true

echo "==> backlog simulation"
./scripts/simulate-backlog.sh 2>&1 | tee "${EV}/backlog-simulation.txt" || true

if command -v trivy >/dev/null; then
  run trivy-image.txt trivy image --severity HIGH,CRITICAL --ignore-unfixed "${IMAGE}" || true
fi

if [[ -n "${AWS_PROFILE:-}" ]]; then
  run tf-plan.txt bash -c "terraform -chdir=infra plan -input=false -no-color" || true
else
  echo "AWS_PROFILE unset — skipped terraform plan" | tee "${EV}/tf-plan.txt"
fi

echo "evidence written to ${EV}"

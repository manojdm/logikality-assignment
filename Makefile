PYTHON ?= app/.venv/bin/python
PIP    ?= uv pip --python app/.venv/bin/python
IMAGE  ?= logikality-docproc
GIT_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
export PATH := $(HOME)/.local/bin:/opt/homebrew/bin:$(PATH)

.PHONY: install lint test docker-build docker-run smoke docker-scan e2e \
	simulate-backlog tf-fmt tf-validate tf-lint tf-scan tf-test tf-plan \
	diagram actionlint evidence clean

install:
	uv pip install --python app/.venv/bin/python -r app/requirements.txt -r app/requirements-dev.txt

lint:
	$(PYTHON) -m ruff check app
	$(PYTHON) -m ruff format --check app
	cd app && ../$(PYTHON) -m mypy --strict src
	cd app && ../$(PYTHON) -m mypy tests --disable-error-code=typeddict-item --disable-error-code=return-value --disable-error-code=arg-type --disable-error-code=unused-ignore

test:
	cd app && ../$(PYTHON) -m pytest tests --cov=docproc --cov-report=term-missing --cov-fail-under=90

docker-build:
	docker build --build-arg GIT_SHA=$(GIT_SHA) --build-arg IMAGE_SOURCE=. -t $(IMAGE):$(GIT_SHA) -t $(IMAGE):local .

docker-run:
	docker run --rm -d --name logikality-api -p 18080:8080 $(IMAGE):local

smoke:
	@curl -fsS http://127.0.0.1:18080/ | tee /dev/stderr | grep -q docproc
	@curl -fsS http://127.0.0.1:18080/health | tee /dev/stderr | grep -q ok

docker-scan:
	trivy image --severity HIGH,CRITICAL --ignore-unfixed $(IMAGE):local

e2e:
	./scripts/e2e.sh

simulate-backlog:
	./scripts/simulate-backlog.sh

tf-fmt:
	terraform -chdir=infra fmt -recursive

tf-validate:
	terraform -chdir=infra init -backend=false -input=false -no-color
	terraform -chdir=infra validate -no-color

tf-lint:
	tflint --chdir=infra --recursive --init
	tflint --chdir=infra --recursive

tf-scan:
	@if command -v checkov >/dev/null; then checkov -d infra --framework terraform --compact; \
	elif [ -x .tools/checkov/bin/checkov ]; then .tools/checkov/bin/checkov -d infra --framework terraform --compact; \
	else echo "install checkov (uv tool install checkov)" && exit 1; fi

tf-test:
	terraform -chdir=infra init -backend=false -input=false -no-color
	terraform -chdir=infra test -no-color

tf-plan:
	@test -n "$$AWS_PROFILE" || (echo "Set AWS_PROFILE=<your-profile>" && exit 1)
	terraform -chdir=infra init -backend=false -input=false -no-color
	terraform -chdir=infra plan -input=false -no-color

diagram:
	$(PYTHON) docs/diagrams/architecture.py
	$(PYTHON) docs/diagrams/architecture-future.py

actionlint:
	actionlint

evidence:
	./scripts/collect-evidence.sh

clean:
	docker compose down -v --remove-orphans || true
	docker rm -f logikality-api 2>/dev/null || true
	rm -rf app/.pytest_cache app/.mypy_cache app/.ruff_cache app/.coverage app/htmlcov
	rm -rf infra/.terraform

.PHONY: help ci lint typecheck test-unit test-integration test-e2e export-openapi compose-up observability-up migrate seed seed-prod-like tf-validate ensure-terraform run-ingestion-worker run-processing-worker run-stuck-scanner gen-dev-jwt mint-jwt live-demo

# Explicit -p beats COMPOSE_PROJECT_NAME env so sibling stacks never collide.
COMPOSE_PROJECT ?= doc-pipeline
COMPOSE ?= docker compose -p $(COMPOSE_PROJECT)

TF_VERSION ?= 1.9.8
TF_DIR     := $(CURDIR)/.tools/terraform
TF_BIN     := $(TF_DIR)/terraform
TF_OS      := linux
TF_ARCH    := amd64
TF_ZIP_URL := https://releases.hashicorp.com/terraform/$(TF_VERSION)/terraform_$(TF_VERSION)_$(TF_OS)_$(TF_ARCH).zip
MODULES    := $(wildcard terraform/modules/*)

help:
	@echo "Quality:"
	@echo "  make ci            lint + typecheck + test-unit"
	@echo "  make lint          ruff check + format check"
	@echo "  make typecheck     mypy on src/doc_pipeline"
	@echo "  make test-unit     pytest unit (excludes integration/e2e)"
	@echo "  make test-integration  pytest -m integration"
	@echo "  make test-e2e      pytest -m e2e (may collect 0)"
	@echo ""
	@echo "JWT / live demo:"
	@echo "  make gen-dev-jwt   generate RSA pair → .local/jwt + patch .env"
	@echo "  make mint-jwt      print dev JWT for tenant acme"
	@echo "  make live-demo     create→presign→PUT→PROCESSED against running API"
	@echo ""
	@echo "OpenAPI:"
	@echo "  make export-openapi  write docs/openapi/openapi.{json,yaml}"
	@echo ""
	@echo "Workers:"
	@echo "  make run-ingestion-worker   python -m doc_pipeline.worker.ingestion_main"
	@echo "  make run-processing-worker  python -m doc_pipeline.worker.processing_main"
	@echo "  make run-stuck-scanner      python -m doc_pipeline.worker.stuck_main"
	@echo ""
	@echo "Compose / data / infra:"
	@echo "  make compose-up / observability-up / migrate / seed / seed-prod-like"
	@echo "  make tf-validate   init -backend=false + validate per module and environment root"

ci: lint typecheck test-unit

lint:
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts

typecheck:
	uv run mypy src

test-unit:
	uv run pytest -m "not integration and not e2e" -q

test-integration:
	uv run pytest -m integration -q

test-e2e:
	uv run pytest -m e2e -q; \
	status=$$?; \
	if [ $$status -eq 5 ]; then echo "no e2e tests collected (ok)"; exit 0; fi; \
	exit $$status

gen-dev-jwt:
	uv run python scripts/gen_dev_jwt_keys.py

mint-jwt:
	uv run python scripts/mint_dev_jwt.py

live-demo:
	PYTHONPATH=scripts uv run python scripts/live_ingest_demo.py

export-openapi:
	uv run python scripts/generate_openapi.py

run-ingestion-worker:
	uv run python -m doc_pipeline.worker.ingestion_main

run-processing-worker:
	uv run python -m doc_pipeline.worker.processing_main

run-stuck-scanner:
	uv run python -m doc_pipeline.worker.stuck_main

compose-up:
	$(COMPOSE) up -d --build --wait postgres redis localstack
	docker image prune -af --filter "label=com.docker.compose.project=$(COMPOSE_PROJECT)"

observability-up:
	$(COMPOSE) up -d --build --wait jaeger otel-collector prometheus grafana
	docker image prune -af --filter "label=com.docker.compose.project=$(COMPOSE_PROJECT)"

migrate:
	uv run alembic upgrade head

# Host-side seed: Settings reads gitignored .env (do not `source` PEM values in dash).
seed:
	uv run python scripts/seed_dev_data.py

seed-prod-like:
	uv run python scripts/seed_prod_like.py

ensure-terraform:
	@if [ ! -x "$(TF_BIN)" ]; then \
	  echo "Downloading Terraform $(TF_VERSION) → $(TF_DIR)"; \
	  mkdir -p "$(TF_DIR)"; \
	  curl -fsSL -A "curl/doc-pipeline-tf-validate" "$(TF_ZIP_URL)" -o "$(TF_DIR)/terraform.zip"; \
	  unzip -o "$(TF_DIR)/terraform.zip" -d "$(TF_DIR)"; \
	  rm -f "$(TF_DIR)/terraform.zip"; \
	  chmod +x "$(TF_BIN)"; \
	  "$(TF_BIN)" version; \
	fi

ENVIRONMENTS := terraform/environments/dev terraform/environments/staging terraform/environments/prod

tf-validate: ensure-terraform
	@set -e; \
	for m in $(MODULES); do \
	  echo "=== validating $$m ==="; \
	  (cd "$$m" && "$(TF_BIN)" init -backend=false -input=false >/dev/null && "$(TF_BIN)" validate); \
	done; \
	for e in $(ENVIRONMENTS); do \
	  echo "=== validating $$e ==="; \
	  (cd "$$e" && "$(TF_BIN)" init -backend=false -input=false >/dev/null && "$(TF_BIN)" validate); \
	done; \
	echo "All modules and environments: Success! The configuration is valid."

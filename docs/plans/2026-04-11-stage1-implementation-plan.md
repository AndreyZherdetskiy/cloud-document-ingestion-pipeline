# Cloud Document Ingestion Pipeline — Stage 1 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
> Implementer ≠ Reviewer. **Do not git commit.** No real AWS `terraform apply`.
> Execute per [`AGENTS.md`](../../AGENTS.md) §10.2. Role prompts: [`docs/agentic/role-prompts/`](../agentic/role-prompts/).
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Compose-demoable MVP: FastAPI control plane (documents, presign, jobs, audit, DLQ replay), LocalStack S3→SQS→worker data plane with Virus/OCR/Extract hook stubs, PostgreSQL status+audit, Redis idempotency, OTel→Collector→Prometheus+Jaeger, Terraform modules that `validate` only, live `/v1/docs` bar, `make seed` / `make seed-prod-like`.

**Architecture:** Single Python package `src/doc_pipeline/`. API never streams file bytes — clients PUT to S3 via presigned URL. S3 ObjectCreated → SQS Standard (+DLQ, `maxReceiveCount=5`) → long-poll worker runs hooks and commits status+audit in one PostgreSQL transaction. UUIDv7 PKs only (no dual-id). Auth Stage 1 = JWT RS256 stub/dev issuer. AWS path is Terraform modules + ADOT collector config — never applied to a real account in this run.

> **Current Compose (post–Stage 2):** services are split — `ingestion-worker`, `processing-worker`, and `stuck-scanner` (not a single Compose `worker`). This Stage 1 plan retains historical single-worker task wording; follow Stage 2 plan / live Compose for runtime topology.


**Tech Stack (as of plan date 2026-04-11):** Python 3.12.x; uv; FastAPI 0.115.x; Uvicorn 0.32.x; Pydantic v2.10.x; SQLAlchemy 2.0.x + asyncpg; Alembic 1.14.x; boto3 1.35.x; redis-py 5.2.x; structlog 24.x; PyJWT 2.x (RS256); uuid6 (UUIDv7); tenacity 9.x; OpenTelemetry Python SDK + OTLP; pytest ≥8,<9 + pytest-asyncio 0.24.x; moto 5.x; LocalStack 3.x; Ruff 0.8.x; mypy 1.13.x; Terraform 1.9.x + AWS provider 5.x; Docker Compose 2.x. Images: `python:3.12-slim`, non-root USER. **Current product floor:** `spec.md` §5 (e.g. FastAPI 0.141.x, redis-py 8.1.x, LocalStack 4.14.x).

## Global Constraints

Copy from `PROMPT_COMMON.md` §5 / `AGENTS.md` §2 (every task implicitly includes these):

1. **Control / data plane split** — API never proxies file bytes (ADR-004). Presign PUT to S3.
2. **S3 → SQS → worker**, not S3 → Lambda (ADR-001). **No Kafka.** Work queue = SQS Standard + DLQ (`maxReceiveCount=5`). Celery optional Stage 2 stuck-job scanner only — not Stage 1 Must.
3. **At-least-once** + Redis `SET NX` + status checks. No exactly-once (ADR-002).
4. **Status + audit in one PostgreSQL transaction.** `audit_log` append-only; app must not UPDATE/DELETE it (ADR-003).
5. **Hook interfaces** (`VirusScanHook`, `OcrHook`, `ExtractHook`) with Stage 1 stubs (ADR-005).
6. **Compute target AWS:** ECS Fargate (ADR-006). Local: Compose api + worker. K8s/EKS not Must.
7. **Terraform + OIDC is the only infra change path** (ADR-007). Write modules; do not apply to real AWS.
8. **RACI** in `docs/ownership-raci.md` (ADR-008). App never “fixes” bucket policy at runtime.
9. **Stage 1 demo does not require UI** (ADR-009).
10. **Secrets:** local `.env` / Settings; AWS path SSM + Secrets Manager (ADR-010) — not applied unless human GO.
11. **No RDS sharding Stages 1–3.** Writes only on primary (ADR-011).
12. **UUIDv7 PK everywhere; no dual-id; no composite `(tenant_id, id)` PK** (ADR-012). Natural UNIQUE `(tenant_id, idempotency_key)` on documents. `id` in API **is** that UUID.
13. **Tenant isolation:** every query filtered by `tenant_id` from JWT. Foreign ID → **404**, not 403.
14. **Poison:** after `maxReceiveCount=5` → DLQ; worker deletes SQS message only on success **or after recording terminal FAILED** (document the choice; Stage 1 chooses: delete after terminal FAILED so poison does not burn visibility forever).
15. **Auth Stage 1:** JWT RS256 from stub/dev issuer (local JWKS). Cognito Stage 2.
16. **Pagination:** cursor + `limit` (default 50, max 200). Do not invent `offset`.
17. **Correlation:** `X-Correlation-ID` (accept `X-Correlation-Id`); UUIDv7; invalid → **422**; generate if missing; echo; bind into structlog, audit, current span. Never log full presigned URLs.
18. **OpenAPI bar** (from-zero §2.1): `/v1/docs` enabled locally; every operation `summary`+`description`; Field descriptions; JWT/`Idempotency-Key` Header descriptions; `responses=` for codes actually raised; no `spec.md`/ADR in OpenAPI prose.
19. **Observability:** OTel SDK → Collector. Local: Prometheus + Grafana + **Jaeger** (not Tempo). AWS Terraform path: ADOT → CloudWatch EMF + X-Ray. Apps export **only OTLP**. Metric attributes: `tenant_slug`, `document_type`, `status`, `hook` — never `document_id` / `correlation_id`.
20. **Quality:** Python 3.12; pytest **8** (`pytest>=8,<9`); `--import-mode=importlib --strict-markers`; no pytest 9 `strict = true`; no TOML `strict_markers`. Behavioral tests only — reject inventory/`is_file`/markdown-grep.
21. **Images:** non-root USER; no `COPY .env`.
22. **Do not declare Stage Done.** Evidence: local SDD harness (gitignored): Stage 1 DoD evidence file.
23. **Anti-copy:** no Hub dual-id/Kafka/HMAC-as-bus; no billing ledger/Stripe; no OFOM gRPC/saga; no RAG/LangGraph; no Tempo; no EKS-as-Must; no Textract-as-Stage1-Must.
24. **No git commit / push / gh / real AWS apply** without explicit human command.
25. **Imports at module top.** No `Task N` left in application code after a task ships.
26. **Frozen ports:** api 8000, postgres 5432, redis 6379, localstack 4566, OTLP 4317/4318, prometheus 9090, grafana 3000, jaeger 16686. Worker has no public host port.
27. **Settings** from `.env` only (`env_file=".env"`, `extra="ignore"`). Empty `OTEL_SDK_DISABLED=` must not crash bool parse.
28. **MIME allowlist + max size** from tenant `config_json` (default 50 MB). Invalid state transition → HTTP 409 / worker error, status unchanged.
29. **Rate limit** Stage 1: Redis token bucket 100 req/min per tenant (spec §8.3).

**Stage 1 Must NOT include:** Cognito, Textract, ClamAV vendor, webhooks HMAC, Celery as ingestion bus, Vite UI, EKS, Kafka, dual-id, `job_steps` table, `DELETE` document GDPR, real AWS apply, git commits.

---

## File map (Stage 1)

| Path | Responsibility |
|------|----------------|
| `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example` | Tooling, deps, demo env template |
| `src/doc_pipeline/main.py` | `create_app()` factory, OpenAPI metadata, lifespan |
| `src/doc_pipeline/config/settings.py` | Pydantic Settings from `.env` |
| `src/doc_pipeline/logging.py` | structlog JSON + redaction |
| `src/doc_pipeline/observability/otel.py` | MeterProvider + TracerProvider OTLP |
| `src/doc_pipeline/domain/ids.py` | `generate_uuidv7() -> UUID` |
| `src/doc_pipeline/domain/enums.py` | DocumentType/Status, JobStatus, UploadStatus, ActorType, … |
| `src/doc_pipeline/domain/state_machine.py` | Document transitions; invalid → error |
| `src/doc_pipeline/domain/hooks/base.py` | Protocol / ABC for Virus/OCR/Extract |
| `src/doc_pipeline/domain/hooks/stubs.py` | Deterministic stubs |
| `src/doc_pipeline/domain/models/*.py` | SQLAlchemy 2 mapped classes |
| `src/doc_pipeline/domain/schemas/*.py` | Pydantic request/response DTOs |
| `src/doc_pipeline/domain/services/*.py` | documents, uploads, jobs, audit, dlq |
| `src/doc_pipeline/infrastructure/db/` | async engine, session, base |
| `src/doc_pipeline/infrastructure/cache/redis.py` | Redis client, idempotency, rate limit |
| `src/doc_pipeline/infrastructure/aws/s3.py` | Presign + HeadObject helpers |
| `src/doc_pipeline/infrastructure/aws/sqs.py` | Receive/delete/redrive helpers |
| `src/doc_pipeline/api/middleware/correlation.py` | UUIDv7 correlation header |
| `src/doc_pipeline/api/deps.py` | JWT principal, DB session, tenant filter |
| `src/doc_pipeline/api/errors.py` | RFC 7807 Problem Details |
| `src/doc_pipeline/api/v1/{documents,uploads,jobs,audit,admin,health}.py` | HTTP routes |
| `src/doc_pipeline/worker/consumer.py` | SQS long-poll loop |
| `src/doc_pipeline/worker/handlers.py` | Process S3 event → hooks → status |
| `src/doc_pipeline/worker/__main__.py` | Worker entrypoint |
| `alembic.ini`, `alembic/env.py`, `alembic/versions/` | Migrations (top-level alembic/) |
| `infra/localstack/init-aws.sh` | Bucket, queue, DLQ, event notify |
| `infra/otel/collector.yaml` | OTLP → Prometheus + Jaeger |
| `infra/prometheus/`, `infra/grafana/` | Scrape + dashboards |
| `deploy/Dockerfile.api`, `deploy/Dockerfile.worker` | Non-root images |
| `docker-compose.yml`, `docker-compose.test.yml` | Local stack |
| `terraform/modules/{networking,s3,sqs,ecs,rds,elasticache,alb,iam,ecr,cloudwatch,kms,secrets,adot}/` | IaC modules |
| `terraform/environments/{dev,staging,prod}/` | Env roots + `*.tfvars.example` |
| `scripts/seed_dev_data.py`, `scripts/seed_prod_like.py`, `scripts/generate_openapi.py` | Seed + OpenAPI export |
| `tests/unit/test_openapi_docs.py` | `/v1/docs` quality lock |
| `docs/runbooks/*.md`, `docs/slo.md`, `docs/architecture.md` | Ops EN docs |
| `.github/workflows/{ci,integration,terraform-plan,terraform-apply-staging,terraform-apply-prod}.yml` | CI stubs (no real apply secrets) |

---

## Spec §3.3 Must → tasks

| Must (spec §3.3) | Tasks |
|------------------|-------|
| API: documents CRUD metadata, presign, job statuses, audit read | 7–9 |
| Pipeline: S3 → SQS → single worker (ingestion + processing stubs) | 1, 10–11 |
| PostgreSQL schema v1 + Alembic | 5 |
| State machine DRAFT→…→PROCESSED/FAILED/CANCELLED | 3, 7, 10 |
| VirusScanHook / OcrHook / ExtractHook stubs | 4, 10 |
| Terraform modules (S3, SQS+DLQ, ECS, RDS, ElastiCache, IAM, ECR, ALB, KMS, CloudWatch, Secrets/SSM) + ADOT | 13 |
| CI: Ruff, mypy, pytest; terraform plan workflow stubs | 0, 14 |
| Observability: JSON logs; ≥5 alerts; Grafana/Prom/Jaeger | 2, 6, 14 |
| Security baseline: encryption story, least-privilege IAM modules, secrets not in git | 0, 8, 13 |
| Ownership RACI + FinOps tags | 13 (RACI already in `docs/ownership-raci.md`; FinOps tags on TF) |
| Live `/v1/docs` bar | 0, 7–9 |
| Seed / seed-prod-like | 12 |
| Stage 1 evidence (no Done label) | 15 |

## Spec §10.3 scenarios 1–8 → tasks

| # | Scenario | Tasks |
|---|----------|-------|
| 1 | Happy path: create → presign → upload (mock) → SQS → worker → `PROCESSED` | 1, 7, 8, 10, 15 |
| 2 | Idempotency: duplicate SQS → one `PROCESSED` | 11 |
| 3 | Invalid MIME → `FAILED` + audit | 10, 12 |
| 4 | Virus stub `clean=false` → `FAILED` | 4, 10 |
| 5 | Invalid status transition → 409 | 3, 7, 9 |
| 6 | After 5 failures → DLQ (redrive) | 1, 11 |
| 7 | Tenant A ≠ B isolation → 404 | 7 |
| 8 | Upload after TTL → CANCELLED / re-presign | 8, 9, 15 (evidence) |
| 9 (TF) | Terraform plan no unexpected destroy (policy check / validate) | 13–14 |

---

### Task 0: uv project, Makefile, Settings stub, OpenAPI lock, health app, CI stub

**Files:**
- Create: `pyproject.toml`, `Makefile`, `.env.example`, `src/doc_pipeline/__init__.py`, `src/doc_pipeline/config/__init__.py`, `src/doc_pipeline/config/settings.py`, `src/doc_pipeline/main.py`, `src/doc_pipeline/api/__init__.py`, `src/doc_pipeline/api/v1/__init__.py`, `src/doc_pipeline/api/v1/health.py`, `src/doc_pipeline/api/router.py`, `tests/unit/test_openapi_docs.py`, `tests/unit/test_settings_otel_disabled.py`, `scripts/generate_openapi.py`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.pre-commit-config.yaml`, `docs/openapi/README.md`
- Modify: `README.md` (one-line quickstart pointer to Makefile only if needed)
- Test: `tests/unit/test_openapi_docs.py`, `tests/unit/test_settings_otel_disabled.py`

**Interfaces:**
- Consumes: nothing from later tasks
- Produces:
  - `create_app() -> FastAPI`
  - `get_settings() -> Settings` (cached)
  - `Settings` fields at minimum: `database_url: str`, `redis_url: str`, `aws_endpoint_url: str | None`, `aws_region: str`, `s3_bucket: str`, `sqs_queue_url: str`, `sqs_dlq_url: str`, `jwt_issuer: str`, `jwt_audience: str`, `jwt_public_key_pem: str`, `stub_virus_clean: bool`, `log_level: str`, `otel_exporter_otlp_endpoint: str`, `otel_service_name: str`, `otel_sdk_disabled: bool` (empty env → `False`)
  - Makefile: `ci`, `lint`, `typecheck`, `test-unit`, `export-openapi`, `compose-up`, `migrate`, `seed`, `seed-prod-like`, `tf-validate`

**Spec:** §5, §9; from-zero §2.1, §2.7, §8.2–8.3

**Acceptance:**
- `uv sync` succeeds; package installable as `doc_pipeline`
- `[tool.pytest.ini_options]` exact from from-zero §2.7 (`addopts = "--import-mode=importlib --strict-markers"`; no `strict = true`; no TOML `strict_markers`)
- `pytest>=8,<9` pinned
- OpenAPI `info.title` = `Cloud Document Ingestion Pipeline`; non-empty `summary` + Markdown `description` covering control vs data plane, no file proxy, presign PUT, JWT, Idempotency-Key, correlation UUIDv7, RFC 7807, tenant **404**
- Tags present with descriptions: `documents`, `uploads`, `jobs`, `audit`, `admin`, `health`
- `servers` includes `http://localhost:8000`
- Health ops have `summary` **and** `description`
- `GET /v1/docs` via TestClient → 200 HTML containing `swagger`
- OpenAPI JSON must not cite product SoT filenames, ADR path prefixes, agent entry filenames, or gitignored harness paths (unit gate lists forbidden substrings)
- Empty `OTEL_SDK_DISABLED=` does not crash Settings
- `.env.example` lists all Settings names with dummy placeholders; no real secrets
- `make ci` = lint + typecheck + test-unit

**Steps:**

- [ ] **Step 1: Write failing OpenAPI + Settings tests**

```python
# tests/unit/test_openapi_docs.py
from fastapi.testclient import TestClient

from doc_pipeline.main import create_app

REQUIRED_TAGS = {"documents", "uploads", "jobs", "audit", "admin", "health"}
# FORBIDDEN_PROSE — see tests/unit/test_openapi_docs.py (gate lists forbidden substrings)


def test_openapi_info_and_tags() -> None:
    app = create_app()
    spec = app.openapi()
    assert spec["info"]["title"] == "Cloud Document Ingestion Pipeline"
    assert spec["info"].get("summary")
    assert spec["info"].get("description")
    desc = spec["info"]["description"]
    for needle in ("presign", "JWT", "404", "problem"):
        assert needle.lower() in desc.lower() or needle in desc
    for bad in FORBIDDEN_PROSE:
        assert bad not in desc
    servers = {s.get("url") for s in spec.get("servers", [])}
    assert "http://localhost:8000" in servers
    tag_names = {t["name"] for t in spec.get("tags", [])}
    assert REQUIRED_TAGS <= tag_names
    for t in spec["tags"]:
        assert t.get("description"), t["name"]


def test_every_operation_has_summary_and_description() -> None:
    spec = create_app().openapi()
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method.startswith("x-"):
                continue
            assert op.get("summary"), f"{method.upper()} {path}"
            assert op.get("description"), f"{method.upper()} {path}"


def test_v1_docs_serves_swagger_html() -> None:
    client = TestClient(create_app())
    r = client.get("/v1/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()
```

```python
# tests/unit/test_settings_otel_disabled.py
from doc_pipeline.config.settings import Settings


def test_empty_otel_sdk_disabled_is_false(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("S3_BUCKET", "dev-doc-pipeline")
    monkeypatch.setenv("SQS_QUEUE_URL", "http://localhost:4566/000000000000/q")
    monkeypatch.setenv("SQS_DLQ_URL", "http://localhost:4566/000000000000/dlq")
    monkeypatch.setenv("JWT_ISSUER", "http://localhost/issuer")
    monkeypatch.setenv("JWT_AUDIENCE", "doc-pipeline")
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", "-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----")
    s = Settings(_env_file=None)
    assert s.otel_sdk_disabled is False
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_openapi_docs.py tests/unit/test_settings_otel_disabled.py -v` → FAIL (import / missing app)

- [ ] **Step 3: Minimal implementation**

```python
# src/doc_pipeline/config/settings.py
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    aws_endpoint_url: str | None = Field(default=None, alias="AWS_ENDPOINT_URL")
    aws_region: str = Field(default="eu-central-1", alias="AWS_REGION")
    s3_bucket: str = Field(alias="S3_BUCKET")
    sqs_queue_url: str = Field(alias="SQS_QUEUE_URL")
    sqs_dlq_url: str = Field(alias="SQS_DLQ_URL")
    jwt_issuer: str = Field(alias="JWT_ISSUER")
    jwt_audience: str = Field(alias="JWT_AUDIENCE")
    jwt_public_key_pem: str = Field(alias="JWT_PUBLIC_KEY_PEM")
    stub_virus_clean: bool = Field(default=True, alias="STUB_VIRUS_CLEAN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(default="doc-pipeline-api", alias="OTEL_SERVICE_NAME")
    otel_sdk_disabled: bool = Field(default=False, alias="OTEL_SDK_DISABLED")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# src/doc_pipeline/main.py
from fastapi import FastAPI

from doc_pipeline.api.v1.health import router as health_router

OPENAPI_TAGS = [
    {"name": "documents", "description": "Document metadata create/list/get."},
    {"name": "uploads", "description": "Presigned S3 upload URLs (files never stream through the API)."},
    {"name": "jobs", "description": "Processing jobs, retry, and cancel."},
    {"name": "audit", "description": "Append-only audit timeline for a document."},
    {"name": "admin", "description": "Platform admin operations such as DLQ replay."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cloud Document Ingestion Pipeline",
        summary="Control-plane API for document ingestion; binary objects go to S3 via presign.",
        description=(
            "## Control vs data plane\n\n"
            "This API manages metadata, jobs, and audit. **Files never stream through the API.** "
            "Clients obtain a **presigned PUT** URL and upload directly to S3.\n\n"
            "## Auth and headers\n\n"
            "- **JWT** Bearer (RS256) identifies the tenant and role.\n"
            "- **Idempotency-Key** on `POST /v1/documents`.\n"
            "- **X-Correlation-ID** must be a UUIDv7 when supplied; the server generates one if missing.\n"
            "- Errors use **RFC 7807** Problem Details (`application/problem+json`).\n"
            "- Cross-tenant IDs return **404**, not 403.\n"
        ),
        openapi_tags=OPENAPI_TAGS,
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        openapi_url="/v1/openapi.json",
        servers=[{"url": "http://localhost:8000", "description": "Local Compose"}],
    )
    app.include_router(health_router, prefix="/v1")
    return app
```

```python
# src/doc_pipeline/api/v1/health.py
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness probe",
    description="Returns 200 when the process is up. Does not check dependencies.",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness probe",
    description="Stage 1 Task 0 stub returns 200. Later tasks require PostgreSQL and Redis.",
)
async def ready() -> dict[str, str]:
    return {"status": "ready"}
```

Pin pytest 8 in `pyproject.toml`:

```toml
[project]
name = "doc-pipeline"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115,<0.116",
  "uvicorn[standard]>=0.32,<0.33",
  "pydantic>=2.10,<2.11",
  "pydantic-settings>=2.6,<3",
]

[dependency-groups]
dev = [
  "pytest>=8,<9",
  "pytest-asyncio>=0.24,<0.25",
  "httpx>=0.28,<0.29",
  "ruff>=0.8,<0.9",
  "mypy>=1.13,<1.14",
  "PyYAML>=6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--import-mode=importlib --strict-markers"
pythonpath = ["src"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = [
    "integration: requires Compose / LocalStack",
    "e2e: live stack",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["doc_pipeline"]
```

Makefile (excerpt):

```makefile
.PHONY: ci lint typecheck test-unit export-openapi
ci: lint typecheck test-unit
lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
typecheck:
	uv run mypy src
test-unit:
	uv run pytest -m "not integration and not e2e" -q
export-openapi:
	uv run python scripts/generate_openapi.py
```

- [ ] **Step 4:** `uv sync && uv run pytest tests/unit/test_openapi_docs.py tests/unit/test_settings_otel_disabled.py -v` → PASS; `make ci` → exit 0

- [ ] **Step 5:** Expand OpenAPI tests later when HTTP routes land (Tasks 7–9). Keep this lock green after every HTTP change.

---

### Task 1: Compose data plane — Postgres, Redis, LocalStack + init bucket/queue/DLQ

**Files:**
- Create: `docker-compose.yml` (postgres, redis, localstack + init), `infra/localstack/init-aws.sh`, `docker-compose.test.yml` (optional slim test overlay)
- Modify: `.env.example` (LocalStack dummy `test`/`test`, URLs pointing at Compose service names for in-network and localhost for host)
- Test: `tests/unit/test_compose_data_plane.py`

**Interfaces:**
- Consumes: frozen ports from Global Constraints
- Produces: Compose services `postgres`, `redis`, `localstack` on network `doc_pipeline`; named volume `doc_pipeline_postgres_data`; after init: S3 bucket `$S3_BUCKET`, SQS queue + DLQ with redrive `maxReceiveCount=5`, S3→SQS notification on `ObjectCreated:*`

**Spec:** §5.4, §7.4, §9; ADR-001; from-zero §2.6, §6

**Acceptance:**
- Host ports: 5432, 6379, 4566
- `depends_on` with `condition: service_healthy` where images support healthchecks
- `restart: unless-stopped`; json-file `max-size: 10m`
- Init script creates DLQ first, then main queue with `RedrivePolicy`, then bucket + notification
- Visibility timeout start **300s**
- No api/worker images required yet
- No Kafka / ZooKeeper / Tempo

**Steps:**

- [ ] **Step 1: Write failing compose parse test**

```python
# tests/unit/test_compose_data_plane.py
from pathlib import Path

import yaml

EXPECTED_PORTS = {
    "postgres": "5432",
    "redis": "6379",
    "localstack": "4566",
}


def test_compose_project_and_data_plane_ports() -> None:
    data = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    # Prefer top-level Compose project name; Makefile may also pass `-p doc_pipeline`.
    assert data.get("name") == "doc_pipeline"
    services = data["services"]
    for svc, host_port in EXPECTED_PORTS.items():
        assert svc in services
        ports = services[svc].get("ports") or []
        flat = " ".join(str(p) for p in ports)
        assert host_port in flat, f"{svc} missing host port {host_port}"


def test_localstack_init_mentions_dlq_and_redrive() -> None:
    script = Path("infra/localstack/init-aws.sh").read_text(encoding="utf-8")
    assert "maxReceiveCount" in script or "maxReceiveCount=5" in script.replace(" ", "")
    assert "dlq" in script.lower()
    assert "mb" in script or "s3api" in script  # bucket create
```

- [ ] **Step 2:** `uv run pytest tests/unit/test_compose_data_plane.py -v` → FAIL

- [ ] **Step 3: Implement Compose + init script**

`infra/localstack/init-aws.sh` must (awslocal or aws --endpoint-url):

1. Create DLQ `{env}-document-ingestion-dlq`
2. Create queue `{env}-document-ingestion` with `VisibilityTimeout=300` and RedrivePolicy `maxReceiveCount=5`
3. Create bucket; enable event notification to the main queue for `s3:ObjectCreated:*`
4. Print queue URLs for operator logs

Compose (as of plan date): Postgres 16, Redis 7, LocalStack 3 with `SERVICES=s3,sqs` (and `kms` if needed for SSE stub). **Current Compose pins:** `postgres:16.15`, `redis:8.10`, `localstack/localstack:4.14.0` (community; CalVer 2026.07.x needs auth token). Mount init script. Use `env_file: .env`. Project/network name `doc_pipeline`.

- [ ] **Step 4:** GREEN pytest; optionally `docker compose up -d postgres redis localstack` and note health in the task report (if Docker unavailable → note BLOCKED for live health; keep files)

---

### Task 2: otel-collector + Prometheus + Jaeger + Grafana (OTLP only)

**Files:**
- Create: `infra/otel/collector.yaml`, `infra/prometheus/prometheus.yml`, `infra/prometheus/alerts.yml`, `infra/grafana/provisioning/datasources/datasource.yml`, `infra/grafana/provisioning/dashboards/dashboards.yml`, `docs/grafana/dashboards/pipeline_overview.json` (minimal panels OK)
- Modify: `docker-compose.yml`, `tests/unit/test_compose_data_plane.py` (or new `tests/unit/test_compose_observability.py`)
- Test: `tests/unit/test_compose_observability.py`

**Interfaces:**
- Collector receivers: OTLP gRPC `:4317`, HTTP `:4318`
- Exporters: Prometheus (scrape target), OTLP/Jaeger (or `otlp` to Jaeger native OTLP)
- Apps will export **only OTLP** to collector — no `prometheus_client` dual path, no Tempo

**Spec:** §8.5; from-zero §2.4, §11; Appendix B (local Prom rules mirror CloudWatch conditions)

**Acceptance:**
- Host ports: 4317, 4318, 9090, 3000, 16686
- Grafana demo `admin`/`admin` via `.env` (`GF_SECURITY_ADMIN_*`)
- Alert rules include DLQ visible > 0 and queue age > 10m (Prom equivalents)
- Jaeger UI reachable; **not Tempo**
- Collector config must not list Tempo exporter

**Steps:**

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_compose_observability.py
from pathlib import Path

import yaml


def test_obs_ports_and_no_tempo() -> None:
    data = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    services = data["services"]
    for svc, port in {
        "otel-collector": "4317",
        "prometheus": "9090",
        "grafana": "3000",
        "jaeger": "16686",
    }.items():
        assert svc in services
        flat = " ".join(str(p) for p in (services[svc].get("ports") or []))
        assert port in flat
    collector = Path("infra/otel/collector.yaml").read_text(encoding="utf-8")
    assert "tempo" not in collector.lower()
    assert "otlp" in collector.lower()
```

- [ ] **Step 2:** RED → add services + configs → GREEN

- [ ] **Step 3:** Document in README one-liner: apps talk OTLP to collector; Grafana `:3000`; Jaeger `:16686`

---

### Task 3: Domain enums + document state machine (TDD)

**Files:**
- Create: `src/doc_pipeline/domain/__init__.py`, `src/doc_pipeline/domain/enums.py`, `src/doc_pipeline/domain/state_machine.py`, `src/doc_pipeline/domain/errors.py`
- Test: `tests/unit/test_state_machine.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `DocumentStatus` StrEnum: `DRAFT`, `UPLOADING`, `UPLOADED`, `QUEUED`, `SCANNING`, `EXTRACTING`, `PROCESSED`, `FAILED`, `CANCELLED`
  - `DocumentType`: `INVOICE`, `KYC`, `CONTRACT`
  - `JobStatus`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `STUCK`, `CANCELLED`
  - `UploadStatus`: `PENDING`, `COMPLETED`, `EXPIRED`, `ABORTED`
  - `ActorType`: `USER`, `SYSTEM`, `OPERATOR`
  - `class InvalidTransitionError(Exception)` with `from_status`, `to_status`
  - `can_transition(src: DocumentStatus, dst: DocumentStatus) -> bool`
  - `transition(src: DocumentStatus, dst: DocumentStatus) -> DocumentStatus` — raises `InvalidTransitionError` if illegal

**Allowed edges (spec §6.7):**
- `DRAFT → UPLOADING`
- `UPLOADING → UPLOADED | CANCELLED`
- `UPLOADED → QUEUED`
- `QUEUED → SCANNING`
- `SCANNING → EXTRACTING | FAILED`
- `EXTRACTING → PROCESSED | FAILED`
- `*` → `CANCELLED` except from terminal `PROCESSED` / `FAILED` / `CANCELLED` (Stage 1 rule: cancel only from non-terminal)

**Spec:** §6.7; ADR-003

**Acceptance:**
- Every allowed edge true; representative illegal edges raise
- Pure domain — no FastAPI/SQLAlchemy imports in `state_machine.py`

**Steps:**

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_state_machine.py
import pytest

from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.errors import InvalidTransitionError
from doc_pipeline.domain.state_machine import can_transition, transition


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (DocumentStatus.DRAFT, DocumentStatus.UPLOADING),
        (DocumentStatus.UPLOADING, DocumentStatus.UPLOADED),
        (DocumentStatus.UPLOADING, DocumentStatus.CANCELLED),
        (DocumentStatus.UPLOADED, DocumentStatus.QUEUED),
        (DocumentStatus.QUEUED, DocumentStatus.SCANNING),
        (DocumentStatus.SCANNING, DocumentStatus.EXTRACTING),
        (DocumentStatus.SCANNING, DocumentStatus.FAILED),
        (DocumentStatus.EXTRACTING, DocumentStatus.PROCESSED),
        (DocumentStatus.EXTRACTING, DocumentStatus.FAILED),
        (DocumentStatus.QUEUED, DocumentStatus.CANCELLED),
    ],
)
def test_allowed_transitions(src: DocumentStatus, dst: DocumentStatus) -> None:
    assert can_transition(src, dst) is True
    assert transition(src, dst) is dst


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (DocumentStatus.DRAFT, DocumentStatus.PROCESSED),
        (DocumentStatus.PROCESSED, DocumentStatus.QUEUED),
        (DocumentStatus.FAILED, DocumentStatus.SCANNING),
        (DocumentStatus.CANCELLED, DocumentStatus.UPLOADING),
    ],
)
def test_invalid_transitions_raise(src: DocumentStatus, dst: DocumentStatus) -> None:
    assert can_transition(src, dst) is False
    with pytest.raises(InvalidTransitionError):
        transition(src, dst)
```

- [ ] **Step 2:** RED → implement enums + machine → GREEN

```python
# src/doc_pipeline/domain/state_machine.py (sketch — implement fully)
ALLOWED: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.DRAFT: frozenset({DocumentStatus.UPLOADING}),
    DocumentStatus.UPLOADING: frozenset({DocumentStatus.UPLOADED, DocumentStatus.CANCELLED}),
    DocumentStatus.UPLOADED: frozenset({DocumentStatus.QUEUED, DocumentStatus.CANCELLED}),
    DocumentStatus.QUEUED: frozenset({DocumentStatus.SCANNING, DocumentStatus.CANCELLED}),
    DocumentStatus.SCANNING: frozenset(
        {DocumentStatus.EXTRACTING, DocumentStatus.FAILED, DocumentStatus.CANCELLED}
    ),
    DocumentStatus.EXTRACTING: frozenset(
        {DocumentStatus.PROCESSED, DocumentStatus.FAILED, DocumentStatus.CANCELLED}
    ),
    DocumentStatus.PROCESSED: frozenset(),
    DocumentStatus.FAILED: frozenset(),
    DocumentStatus.CANCELLED: frozenset(),
}
```

---

### Task 4: Hook contracts + stub virus/OCR/extract (TDD)

**Files:**
- Create: `src/doc_pipeline/domain/hooks/__init__.py`, `src/doc_pipeline/domain/hooks/base.py`, `src/doc_pipeline/domain/hooks/stubs.py`, `src/doc_pipeline/domain/hooks/types.py`
- Test: `tests/unit/test_hooks.py`

**Interfaces:**
- Consumes: `Settings.stub_virus_clean` (or explicit ctor flag)
- Produces:
  - `@dataclass(frozen=True) class HookContext`: `tenant_id: UUID`, `document_id: UUID`, `document_type: DocumentType`, `bucket: str`, `key: str`, `mime_type: str | None`, `checksum_sha256: str | None`
  - `@dataclass(frozen=True) class VirusScanResult`: `clean: bool`, `scanner: str`, `scan_id: str`
  - `@dataclass(frozen=True) class OcrResult`: `provider: str`, `pages: int`, `text_preview: str`, `confidence: float`
  - `@dataclass(frozen=True) class ExtractResult`: `document_type: DocumentType`, `payload: dict[str, object]`
  - `class VirusScanHook(Protocol): async def scan(self, ctx: HookContext) -> VirusScanResult: ...`
  - `class OcrHook(Protocol): async def run(self, ctx: HookContext) -> OcrResult: ...`
  - `class ExtractHook(Protocol): async def run(self, ctx: HookContext, ocr: OcrResult) -> ExtractResult: ...`
  - `StubVirusScanHook(clean: bool = True, sleep_ms: int = 0)`
  - `StubOcrHook`, `StubExtractHook` — deterministic by `document_id` / checksum

**Spec:** §7.6; ADR-005

**Acceptance:**
- Same field names as future Textract/ClamAV adapters
- `StubVirusScanHook(clean=False)` returns `clean=False` (worker maps to FAILED in Task 10)
- Deterministic: same `document_id` → same `scan_id` / OCR preview
- Optional short sleep+jitter injectable for visibility-timeout realism (default 0 in unit tests)

**Steps:**

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_hooks.py
from uuid import UUID

import pytest

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.hooks.types import HookContext

DOC_ID = UUID("01900000-0000-7000-8000-000000000001")


def _ctx() -> HookContext:
    return HookContext(
        tenant_id=UUID("01900000-0000-7000-8000-0000000000aa"),
        document_id=DOC_ID,
        document_type=DocumentType.INVOICE,
        bucket="bucket",
        key="t/d/f.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )


@pytest.mark.asyncio
async def test_virus_stub_clean_true() -> None:
    result = await StubVirusScanHook(clean=True).scan(_ctx())
    assert result.clean is True
    assert result.scanner
    assert result.scan_id


@pytest.mark.asyncio
async def test_virus_stub_clean_false() -> None:
    result = await StubVirusScanHook(clean=False).scan(_ctx())
    assert result.clean is False


@pytest.mark.asyncio
async def test_ocr_and_extract_deterministic() -> None:
    ocr_a = await StubOcrHook().run(_ctx())
    ocr_b = await StubOcrHook().run(_ctx())
    assert ocr_a == ocr_b
    ext = await StubExtractHook().run(_ctx(), ocr_a)
    assert ext.document_type is DocumentType.INVOICE
    assert isinstance(ext.payload, dict)
```

- [ ] **Step 2:** RED → implement → GREEN

---

### Task 5: SQLAlchemy models UUIDv7 + Alembic (tenants, documents, uploads, jobs, audit_log)

**Files:**
- Create: `src/doc_pipeline/domain/ids.py`, `src/doc_pipeline/infrastructure/db/base.py`, `src/doc_pipeline/infrastructure/db/session.py`, `src/doc_pipeline/domain/models/__init__.py`, `src/doc_pipeline/domain/models/tenant.py`, `document.py`, `upload.py`, `job.py`, `audit_log.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/20260414_0001_initial_uuidv7.py`
- Modify: `pyproject.toml` (sqlalchemy, asyncpg, alembic, uuid6), `Makefile` (`migrate`)
- Test: `tests/unit/test_models_uuidv7.py`

**Interfaces:**
- Consumes: enums from Task 3
- Produces:
  - `generate_uuidv7() -> UUID`
  - Mapped models matching spec §6.2–6.6 column-for-column (no `job_steps`, no `public_id`, no BIGINT identity)
  - `documents`: UNIQUE `(tenant_id, idempotency_key)`; indexes `(tenant_id, status)`, `(tenant_id, external_ref)`, `(tenant_id, created_at)`
  - `get_async_sessionmaker(settings) -> async_sessionmaker[AsyncSession]` with `expire_on_commit=False`
  - Alembic async env using `Base.metadata`

**Spec:** §6.0–6.6; ADR-012, ADR-003, ADR-011

**Acceptance:**
- Unit test inspects mapper columns / uniques / indexes (no live DB required for unit)
- Optional integration: `alembic upgrade head` against Compose PG in report
- No dual-id; no composite PK `(tenant_id, id)`

**Steps:**

- [ ] **Step 1: Failing model shape test**

```python
# tests/unit/test_models_uuidv7.py
from sqlalchemy import inspect as sa_inspect

from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant


def test_document_pk_is_uuid_only() -> None:
    mapper = sa_inspect(Document)
    pk_cols = [c.name for c in mapper.primary_key]
    assert pk_cols == ["id"]
    col_names = {c.key for c in mapper.columns}
    assert "public_id" not in col_names
    assert "idempotency_key" in col_names
    assert "tenant_id" in col_names


def test_tenant_slug_unique() -> None:
    table = Tenant.__table__
    uniques = {tuple(u.columns.keys()) for u in table.constraints if hasattr(u, "columns")}
    # also check UniqueConstraint / Index
    assert any("slug" in str(c) for c in table.constraints) or any(
        "slug" in ix.name for ix in table.indexes
    )
```

Expand test to assert UNIQUE name contains `tenant_id` + `idempotency_key` on `documents`.

- [ ] **Step 2:** RED → models + Alembic revision → GREEN

- [ ] **Step 3:** `make migrate` documented; revision creates all five tables

---

### Task 6: Settings hardening, structlog, correlation middleware, RFC 7807, OTel bootstrap

**Files:**
- Create: `src/doc_pipeline/logging.py`, `src/doc_pipeline/observability/__init__.py`, `src/doc_pipeline/observability/otel.py`, `src/doc_pipeline/api/middleware/correlation.py`, `src/doc_pipeline/api/errors.py`, `src/doc_pipeline/api/deps_auth.py` (JWT stub scaffold used in Task 7)
- Modify: `src/doc_pipeline/main.py` (middleware, exception handlers, lifespan OTel), `pyproject.toml` (structlog, opentelemetry-*, PyJWT, cryptography)
- Test: `tests/unit/test_correlation_middleware.py`, `tests/unit/test_problem_details.py`, `tests/unit/test_logging_redaction.py`, `tests/unit/test_otel_cardinality.py`

**Interfaces:**
- Consumes: `create_app`, `Settings`, `generate_uuidv7`
- Produces:
  - `configure_logging(settings) -> None`
  - `configure_otel(service_name: str, settings) -> None` — no-op if `otel_sdk_disabled`
  - Middleware: read `X-Correlation-ID` or `X-Correlation-Id`; invalid non-UUIDv7 → **422** Problem Details; missing → generate; echo response header; bind to contextvar for structlog
  - `problem_response(status: int, title: str, detail: str, type_: str = "about:blank") -> JSONResponse` with `media_type="application/problem+json"`
  - Handlers for `RequestValidationError`, `InvalidTransitionError` → 422 / 409

**Spec:** §7.1, §7.3, §8.5; from-zero §2.4–2.5

**Acceptance:**
- Never log full presigned URLs (redact `presigned_url`, `https://` query signatures)
- Metric helper rejects `document_id` / `correlation_id` attributes
- Resource: `service.name` = `doc-pipeline-api` | `doc-pipeline-worker`

**Steps:**

- [ ] **Step 1: Tests**

```python
# tests/unit/test_correlation_middleware.py
from fastapi.testclient import TestClient

from doc_pipeline.main import create_app


def test_missing_correlation_generates_uuidv7() -> None:
    client = TestClient(create_app())
    r = client.get("/v1/health")
    assert r.status_code == 200
    cid = r.headers.get("X-Correlation-ID") or r.headers.get("x-correlation-id")
    assert cid
    # UUIDv7 version nibble is 7
    assert cid[14] == "7"


def test_invalid_correlation_422() -> None:
    client = TestClient(create_app())
    r = client.get("/v1/health", headers={"X-Correlation-ID": "not-a-uuid"})
    assert r.status_code == 422
    assert r.headers.get("content-type", "").startswith("application/problem+json")
```

```python
# tests/unit/test_otel_cardinality.py
import pytest

from doc_pipeline.observability.otel import assert_low_cardinality_attrs


def test_rejects_high_card_keys() -> None:
    with pytest.raises(ValueError):
        assert_low_cardinality_attrs({"document_id": "x"})
    with pytest.raises(ValueError):
        assert_low_cardinality_attrs({"correlation_id": "y"})
    assert_low_cardinality_attrs({"tenant_slug": "acme", "document_type": "INVOICE"})
```

- [ ] **Step 2:** RED → implement middleware + OTel + Problem Details → GREEN

- [ ] **Step 3:** Wire lifespan shutdown to flush providers

---

### Task 7: FastAPI documents create/list/get + JWT stub + tenant 404 + Idempotency-Key

**Files:**
- Create: `src/doc_pipeline/domain/schemas/documents.py`, `src/doc_pipeline/domain/services/document_service.py`, `src/doc_pipeline/api/v1/documents.py`, `src/doc_pipeline/api/deps.py`, `src/doc_pipeline/infrastructure/cache/redis.py`, `tests/fixtures/jwt_keys.py` (or generate in conftest)
- Modify: `src/doc_pipeline/main.py`, `tests/unit/test_openapi_docs.py` (expand: JWT/`Idempotency-Key` descriptions, Field descriptions, 401/404 examples, no integer `id`)
- Test: `tests/unit/test_documents_api.py`, `tests/unit/test_tenant_isolation.py` (TestClient + DB override / SQLite only if async PG fixture; prefer `@pytest.mark.integration` for real PG — unit may mock service layer **or** use async PG from Compose)

**Interfaces:**
- Consumes: models, state machine, Settings, Redis, correlation middleware
- Produces:
  - `Principal` dataclass: `sub: str`, `tenant_id: UUID`, `roles: frozenset[str]`
  - `get_current_principal(authorization: Annotated[str, Header(...)]) -> Principal` — 401 if missing/invalid
  - `POST /v1/documents` with `Idempotency-Key` header (required); body fields per §7.2; 201 + DRAFT; duplicate key → 200 same document or 409 per spec (Stage 1: return **200** with existing document when UNIQUE hits and payload matches; **409** if key reused with different payload)
  - `GET /v1/documents/{document_id}` — tenant scoped; foreign → **404**
  - `GET /v1/documents` — filters `status`, `document_type`, `external_ref`, cursor+limit
  - Rate limit: 429 when Redis bucket exhausted
  - Ready probe: fail if PG down (upgrade Task 0 stub)

**Spec:** §2.2, §7.1–7.3, §8.3; ADR-012

**Acceptance:**
- OpenAPI: every new operation has summary+description; Header descriptions on Authorization and Idempotency-Key; `Body(openapi_examples=…)` on create; responses include 401, 404, 409, 422, 429 as raised
- Enums in schema — not bare `str` for status/type
- Cursor pagination only
- Idempotency: same key + matching payload → **200** same `id`; same key + different payload → **409** Problem Details (behavioral tests)
- Rate limit: Redis bucket exhausted → **429** Problem Details (unit with fake Redis override)

**Steps:**

- [ ] **Step 1: OpenAPI expansion + behavioral tests**

```python
# tests/unit/test_tenant_isolation.py
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

# Use project TestClient fixtures that inject tenant A JWT and seed document owned by A.


@pytest.mark.asyncio
async def test_foreign_document_returns_404(api_client_tenant_a, document_id_tenant_b) -> None:
    r = await api_client_tenant_a.get(f"/v1/documents/{document_id_tenant_b}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
```

```python
def test_openapi_documents_headers_and_examples() -> None:
    spec = create_app().openapi()
    create_op = spec["paths"]["/v1/documents"]["post"]
    assert create_op.get("summary") and create_op.get("description")
    params = {p["name"]: p for p in create_op.get("parameters", [])}
    assert "Idempotency-Key" in params
    assert params["Idempotency-Key"].get("description")
    assert create_op.get("requestBody")
    create_responses = create_op.get("responses", {})
    assert "409" in create_responses, "POST /v1/documents must document 409 for idempotency conflict"
    assert "429" in create_responses, "POST /v1/documents must document 429 for rate limit"
    retry_responses = spec["paths"]["/v1/jobs/{job_id}/retry"]["post"].get("responses", {})
    assert "409" in retry_responses, "POST /v1/jobs/{job_id}/retry must document 409 for invalid transition"
```

```python
# tests/unit/test_documents_api.py
import pytest
from httpx import ASGITransport, AsyncClient

CREATE_BODY = {
    "document_type": "INVOICE",
    "external_ref": "inv-001",
    "file_name": "invoice.pdf",
    "content_type": "application/pdf",
    "checksum_sha256": "a" * 64,
}


@pytest.mark.asyncio
async def test_idempotency_same_key_same_payload_returns_200_same_id(
    api_client_tenant_a,
) -> None:
    headers = {"Idempotency-Key": "idem-001"}
    r1 = await api_client_tenant_a.post("/v1/documents", json=CREATE_BODY, headers=headers)
    assert r1.status_code == 201
    doc_id = r1.json()["id"]

    r2 = await api_client_tenant_a.post("/v1/documents", json=CREATE_BODY, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_idempotency_same_key_different_payload_returns_409(
    api_client_tenant_a,
) -> None:
    headers = {"Idempotency-Key": "idem-002"}
    r1 = await api_client_tenant_a.post("/v1/documents", json=CREATE_BODY, headers=headers)
    assert r1.status_code == 201

    conflicting = {**CREATE_BODY, "external_ref": "inv-002"}
    r2 = await api_client_tenant_a.post("/v1/documents", json=conflicting, headers=headers)
    assert r2.status_code == 409
    assert r2.headers["content-type"].startswith("application/problem+json")
    assert r2.json().get("title") or r2.json().get("detail")


@pytest.mark.asyncio
async def test_rate_limit_exhausted_returns_429(
    api_client_tenant_a,
    fake_redis_rate_limit_exhausted,
) -> None:
    r = await api_client_tenant_a.post(
        "/v1/documents",
        json=CREATE_BODY,
        headers={"Idempotency-Key": "idem-rate-limit"},
    )
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
```

`fake_redis_rate_limit_exhausted` fixture: override Redis rate-limit dependency so token bucket returns exhausted (no live Redis required for this unit test).

Implement fixtures in `tests/conftest.py`:

```python
# tests/conftest.py (excerpt)
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()


def mint_token(*, tenant_id: str, roles: list[str], sub: str = "user-1") -> str:
    return jwt.encode(
        {
            "sub": sub,
            "tenant_id": tenant_id,
            "roles": roles,
            "iss": "http://localhost/issuer",
            "aud": "doc-pipeline",
        },
        PRIVATE_PEM,
        algorithm="RS256",
    )
```

Wire `Settings.jwt_public_key_pem` to `PUBLIC_PEM` in fixtures. Use `ROLE_API_CLIENT` for create/get; separate clients for other tenants to prove 404.

- [ ] **Step 2:** RED → implement routes/services → GREEN

- [ ] **Step 3:** `make export-openapi` updates `docs/openapi/openapi.json` + `.yaml`; unit test that snapshot path set equals `create_app().openapi()` paths

- [ ] **Step 4:** Invalid transition via cancel/retry paths lands primarily in Task 9. Keep domain 409 source locked here:

```python
def test_invalid_transition_raises() -> None:
    from doc_pipeline.domain.enums import DocumentStatus
    from doc_pipeline.domain.errors import InvalidTransitionError
    from doc_pipeline.domain.state_machine import transition

    import pytest

    with pytest.raises(InvalidTransitionError):
        transition(DocumentStatus.PROCESSED, DocumentStatus.QUEUED)
```

HTTP handlers that catch `InvalidTransitionError` must map it to **409** Problem Details (Task 9 cancel/retry).
---

### Task 8: Presign + moto unit (required_headers, key layout, TTL)

**Files:**
- Create: `src/doc_pipeline/infrastructure/aws/s3.py`, `src/doc_pipeline/domain/schemas/uploads.py`, `src/doc_pipeline/domain/services/upload_service.py`, `src/doc_pipeline/api/v1/uploads.py`
- Modify: `main.py` router include; OpenAPI tests
- Test: `tests/unit/test_presign_moto.py`

**Interfaces:**
- Consumes: Document model (must be DRAFT or re-presign from EXPIRED/CANCELLED-upload path), boto3 client factory using `AWS_ENDPOINT_URL` when set
- Produces:
  - `build_object_key(tenant_id: UUID, document_id: UUID, file_name: str) -> str` → `{tenant_id}/{document_id}/{sanitized_filename}`
  - `create_presigned_put(...) -> PresignResult` with `upload_id`, `presigned_url`, `method="PUT"`, `expires_at`, `s3_bucket`, `s3_key`, `required_headers: dict` including `Content-Type`, checksum header, SSE-KMS header keys
  - `POST /v1/uploads/presign` body: `document_id`, `content_type`, `checksum_sha256`
  - On success: document `DRAFT → UPLOADING`; create `uploads` row `PENDING` with TTL default **15 minutes** (max 60 from tenant config)
  - Never log `presigned_url`

**Spec:** §7.2, §5.4, §8.3; ADR-004

**Acceptance:**
- moto 5 unit: URL contains bucket/key; method PUT; TTL ≤ 15*60 seconds for default
- MIME not in tenant allowlist → 400 Problem Details (or 422) **before** issuing URL; invalid MIME that slips to worker is Task 10 scenario 3
- OpenAPI example on presign body; Field descriptions

**Steps:**

- [ ] **Step 1: moto failing test**

```python
# tests/unit/test_presign_moto.py
from datetime import UTC, datetime, timedelta
from uuid import UUID

import boto3
from moto import mock_aws

from doc_pipeline.infrastructure.aws.s3 import build_object_key, create_presigned_put


@mock_aws
def test_presign_shape_and_key_layout() -> None:
    bucket = "dev-doc-pipeline"
    region = "eu-central-1"
    client = boto3.client("s3", region_name=region)
    client.create_bucket(
        Bucket=bucket,
        CreateBucketConfiguration={"LocationConstraint": region},
    )
    tenant_id = UUID("01900000-0000-7000-8000-0000000000aa")
    document_id = UUID("01900000-0000-7000-8000-000000000001")
    key = build_object_key(tenant_id, document_id, "invoice.pdf")
    assert key == f"{tenant_id}/{document_id}/invoice.pdf"
    result = create_presigned_put(
        client,
        bucket=bucket,
        key=key,
        content_type="application/pdf",
        checksum_sha256="b" * 64,
        expires_in=900,
    )
    assert result.method == "PUT"
    assert bucket in result.presigned_url
    assert "Content-Type" in result.required_headers
    assert result.expires_at <= datetime.now(UTC) + timedelta(seconds=901)
```

- [ ] **Step 2:** RED → implement S3 helper + HTTP → GREEN

- [ ] **Step 3:** Test expired upload path unit at service level: if `uploads.expires_at < now` and still PENDING, mark EXPIRED / allow document CANCELLED or re-presign from UPLOADING (scenario 8) — implement `expire_stale_upload(upload, now) -> DocumentStatus` helper tested here; HTTP cancel/re-presign completed in Task 9 if needed

```python
def test_expired_upload_marks_expired(frozen_now) -> None:
    from doc_pipeline.domain.services.upload_service import expire_stale_upload
    from doc_pipeline.domain.enums import UploadStatus

    status = expire_stale_upload(
        expires_at=frozen_now - timedelta(seconds=1),
        current=UploadStatus.PENDING,
        now=frozen_now,
    )
    assert status is UploadStatus.EXPIRED
```

---

### Task 9: Jobs / audit / admin DLQ replay HTTP + OpenAPI export

**Files:**
- Create: `src/doc_pipeline/api/v1/jobs.py`, `audit.py`, `admin.py`, `src/doc_pipeline/domain/schemas/jobs.py`, `audit.py`, `admin.py`, `src/doc_pipeline/domain/services/job_service.py`, `audit_service.py`, `dlq_service.py`, `src/doc_pipeline/infrastructure/aws/sqs.py`
- Modify: OpenAPI lock tests; `scripts/generate_openapi.py`
- Test: `tests/unit/test_jobs_rbac.py`, `tests/unit/test_audit_api.py`, `tests/unit/test_dlq_replay.py`, `tests/unit/test_uploads_expired_http.py`

**Interfaces:**
- Consumes: Principal roles (`ROLE_OPERATOR`, `ROLE_PLATFORM_ADMIN`, …), SQS client
- Produces:
  - `GET /v1/jobs/{job_id}`, `GET /v1/jobs` filters `status`, `document_id`, `older_than`, cursor+limit
  - `POST /v1/jobs/{job_id}/retry` — Operator; only `FAILED`/`STUCK` → 409 otherwise; audit `JOB_RETRY`
  - `POST /v1/jobs/{job_id}/cancel` — Operator/Admin; uses state machine; 409 invalid
  - `GET /v1/audit` — **requires** `document_id`; optional `from`, `to`, `event_type`
  - `GET /v1/documents/{id}` enrichment: job summary + last 5 audit events
  - `POST /v1/admin/dlq/replay` — Platform Admin; body `{ "message_ids": ["..."] }` → start message move/redrive to main queue (LocalStack-compatible wrapper)
  - `make export-openapi` green; snapshot path equality test

**Spec:** §7.2, §2.2 J-02/J-03/J-04; Appendix runbooks later Task 14

**Acceptance:**
- RBAC: API client cannot retry or replay DLQ → 403
- 409 on invalid job/document transitions
- OpenAPI documents 403 on RBAC routes
- Spec §10.3.8 (scenario 8): expired PENDING upload → `EXPIRED` / document `CANCELLED` or re-presign path; HTTP re-presign after TTL succeeds (Task 8 `expire_stale_upload` unit helper; HTTP flow here)

**Steps:**

- [ ] **Step 1: Tests**

```python
def test_retry_invalid_status_409(operator_client, succeeded_job_id) -> None:
    r = operator_client.post(f"/v1/jobs/{succeeded_job_id}/retry")
    assert r.status_code == 409


def test_dlq_replay_forbidden_for_api_client(api_client) -> None:
    r = api_client.post("/v1/admin/dlq/replay", json={"message_ids": ["abc"]})
    assert r.status_code == 403


def test_audit_requires_document_id(operator_client) -> None:
    r = operator_client.get("/v1/audit")
    assert r.status_code in (400, 422)
```

```python
# tests/unit/test_uploads_expired_http.py — spec §10.3.8 scenario 8 (HTTP cancel/re-presign)
from datetime import timedelta

import pytest


@pytest.mark.asyncio
async def test_expired_upload_cancel_and_represign_allowed(
    api_client_tenant_a,
    draft_document_id,
    frozen_now,
    db_session,
) -> None:
    """After presign TTL: upload EXPIRED; document CANCELLED or UPLOADING reset; re-presign returns new URL."""
    presign_body = {
        "document_id": str(draft_document_id),
        "content_type": "application/pdf",
        "checksum_sha256": "c" * 64,
    }
    r1 = await api_client_tenant_a.post("/v1/uploads/presign", json=presign_body)
    assert r1.status_code in (200, 201)
    upload_id = r1.json()["upload_id"]

    # Simulate TTL expiry (fixture sets uploads.expires_at in the past; expire_stale_upload from Task 8)
    await expire_upload_fixture(db_session, upload_id, frozen_now - timedelta(seconds=1))

    r_cancel = await api_client_tenant_a.post(
        f"/v1/documents/{draft_document_id}/cancel",
    )
    assert r_cancel.status_code in (200, 204)
    doc = (await api_client_tenant_a.get(f"/v1/documents/{draft_document_id}")).json()
    assert doc["status"] in ("CANCELLED", "UPLOADING")

    r2 = await api_client_tenant_a.post("/v1/uploads/presign", json=presign_body)
    assert r2.status_code in (200, 201)
    assert r2.json()["presigned_url"]
    assert r2.json()["upload_id"] != upload_id
```

- [ ] **Step 2:** RED → implement → GREEN; export OpenAPI

---

### Task 10: Worker SQS consumer + hooks → PROCESSED/FAILED + audit txn

**Files:**
- Create: `src/doc_pipeline/worker/__init__.py`, `consumer.py`, `handlers.py`, `__main__.py`, `deploy/Dockerfile.api`, `deploy/Dockerfile.worker`, Compose services `api` + `worker`
- Modify: `docker-compose.yml`, Settings for worker service name
- Test: `tests/unit/test_worker_handler.py`, `tests/integration/test_happy_path_localstack.py` (marked integration)

**Interfaces:**
- Consumes: hooks, state machine, models, SQS/S3 helpers
- Produces:
  - `parse_s3_event_message(body: str | dict) -> S3IngestEvent` with `bucket`, `object_key`, `etag`, `tenant_id`, `document_id` parsed from key `{tenant_id}/{document_id}/...`
  - `async def handle_ingest_event(session, hooks, event, settings) -> DocumentStatus`
  - Flow: load document → `UPLOADED` (if from S3) → `QUEUED` → `SCANNING` (virus) → `EXTRACTING` (ocr+extract) → `PROCESSED`; on virus `clean=false` or hook error → `FAILED` + `failure_reason`
  - **Every transition** inserts `audit_log` in the **same** DB transaction as status update
  - MIME allowlist check: invalid → `FAILED` + audit (scenario 3)
  - Delete SQS message after success **or** after terminal FAILED is committed
  - SIGTERM: finish in-flight or leave message invisible until timeout (document in worker README comment / runbook)
  - OTel: `service.name=doc-pipeline-worker`; metrics `documents_processed`, `hook_duration` with low-card attrs

**Spec:** §4.3–4.4, §7.4, §7.6, §10.3.1/3/4; ADR-001–005

**Acceptance:**
- Unit: virus clean false → FAILED + audit row added (session mock/`AsyncMock` only for awaitables)
- Unit: happy stub path ends PROCESSED
- Dockerfile: non-root USER; no `COPY .env`; HEALTHCHECK on api
- Compose api:8000; worker no host ports

**Steps:**

- [x] **Step 1: Handler unit tests**

```python
# tests/unit/test_worker_handler.py
import pytest

from doc_pipeline.domain.enums import DocumentStatus
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.worker.handlers import handle_ingest_event


def event_for(document) -> dict:
    """Build the logical S3 ingest event the worker parses (not raw SNS wrapping)."""
    return {
        "schema_version": "1",
        "event_source": "aws:s3",
        "event_name": "ObjectCreated:Put",
        "bucket": document.s3_bucket,
        "object_key": document.s3_key,
        "etag": "abc",
        "tenant_id": str(document.tenant_id),
        "document_id": str(document.id),
    }


@pytest.mark.asyncio
async def test_virus_fail_sets_failed(db_session, uploaded_document, settings) -> None:
    from sqlalchemy import select

    from doc_pipeline.domain.models.audit_log import AuditLog

    hooks = (
        StubVirusScanHook(clean=False),
        StubOcrHook(),
        StubExtractHook(),
    )
    status = await handle_ingest_event(
        db_session,
        hooks,
        event_for(uploaded_document),
        settings,
    )
    assert status is DocumentStatus.FAILED
    rows = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.document_id == uploaded_document.id,
                AuditLog.to_status == DocumentStatus.FAILED.value,
            )
        )
    ).all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_happy_path_processed(db_session, uploaded_document, settings) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    status = await handle_ingest_event(db_session, hooks, event_for(uploaded_document), settings)
    assert status is DocumentStatus.PROCESSED
```
- [x] **Step 2:** RED → implement handler + consumer loop → GREEN

- [x] **Step 3:** Add Compose `api`/`worker` services with `env_file: .env`, `depends_on` healthy PG/Redis/LocalStack, `stop_grace_period: 30s`

- [x] **Step 4:** Integration (optional in CI): mark `@pytest.mark.integration` happy path against LocalStack — deselected by default in `make test-unit`

---

### Task 11: Idempotency duplicate SQS; poison → DLQ

**Files:**
- Create: `src/doc_pipeline/domain/services/idempotency.py`, extend worker handler
- Modify: `infra/localstack/init-aws.sh` if redrive needs tuning; `tests/unit/test_sqs_idempotency.py`, `tests/integration/test_dlq_redrive.py`
- Test: unit + marked integration

**Interfaces:**
- Consumes: Redis, document status
- Produces:
  - `async def acquire_processing_lock(redis, document_id: UUID, ttl_seconds: int = 600) -> bool` — `SET key NX EX`
  - If document already `PROCESSED` / `FAILED` terminal: ACK/delete message without re-running hooks (duplicate delivery → one terminal outcome)
  - Simulate receive count: after 5 handler failures without terminal write, message lands on DLQ (LocalStack redrive) — integration test
  - Document poison policy in `docs/runbooks/dlq-replay.md` (full prose in Task 14; stub pointer OK here)

**Spec:** §10.3.2, §10.3.6; ADR-002

**Acceptance:**
- Unit: two `handle_ingest_event` calls → still one PROCESSED; hooks invoked once (mock call count)
- Integration: force failures → DLQ depth ≥ 1 (Compose)

**Steps:**

- [x] **Step 1:**

```python
@pytest.mark.asyncio
async def test_duplicate_delivery_one_processed(db_session, redis, uploaded_document, settings, hooks_clean, monkeypatch) -> None:
    calls = {"n": 0}
    real_scan = hooks_clean[0].scan

    async def counting_scan(ctx):
        calls["n"] += 1
        return await real_scan(ctx)

    monkeypatch.setattr(hooks_clean[0], "scan", counting_scan)
    event = event_for(uploaded_document)
    s1 = await handle_ingest_event(db_session, hooks_clean, event, settings)
    s2 = await handle_ingest_event(db_session, hooks_clean, event, settings)
    assert s1 is DocumentStatus.PROCESSED
    assert s2 is DocumentStatus.PROCESSED
    assert calls["n"] == 1
```

- [x] **Step 2:** RED → lock + short-circuit → GREEN

- [x] **Step 3:** Integration test for DLQ (mark integration) asserting ApproximateNumberOfMessagesVisible on DLQ after poison

---

### Task 12: Seed + seed-prod-like

**Files:**
- Create: `src/doc_pipeline/scripts/` or top-level `scripts/seed_dev_data.py`, `scripts/seed_prod_like.py`, `src/doc_pipeline/seed/__init__.py` helpers imported by scripts
- Modify: `Makefile` `seed` / `seed-prod-like`
- Test: `tests/unit/test_seed_functions.py`

**Interfaces:**
- Consumes: Settings, models, LocalStack boto3
- Produces:
  - `async def seed_dev(session, s3, settings) -> SeedReport` — tenant slug **`acme`**, JWT bootstrap note printed (not secrets in git), 1–3 objects in bucket, queues exist (check)
  - `async def seed_prod_like(session, s3, settings) -> SeedReport` — several tenants; mix INVOICE/KYC/CONTRACT; one virus-stub-fail fixture row; one invalid MIME fixture; enough rows for dashboards
  - Idempotent upserts on natural keys (`tenants.slug`, documents idempotency keys)

**Spec:** from-zero §2.3; §1.5 document types

**Acceptance:**
- Tests **import** seed modules and call functions (with mocks or test DB) — do not grep scripts
- No CloudWatch seeding

**Steps:**

- [x] **Step 1:**

```python
# tests/unit/test_seed_functions.py
import pytest

from doc_pipeline.seed.dev import seed_dev


@pytest.mark.asyncio
async def test_seed_dev_upserts_acme(db_session, s3_moto, settings) -> None:
    report1 = await seed_dev(db_session, s3_moto, settings)
    report2 = await seed_dev(db_session, s3_moto, settings)
    assert report1.tenant_slug == "acme"
    assert report2.tenant_slug == "acme"
    assert report2.tenants_created == 0
```

- [x] **Step 2:** Implement → GREEN; Makefile targets call `uv run python scripts/seed_dev_data.py`

---

### Task 13: Terraform modules + tf-validate + FinOps tags + CloudWatch JSON + ADOT module

**Files:**
- Create under `terraform/modules/`: `networking`, `s3`, `sqs`, `ecs`, `rds`, `elasticache`, `alb`, `iam` (task roles + GitHub OIDC), `ecr`, `cloudwatch` (dashboard JSON + Appendix B alarms), `kms`, `secrets`, `adot` (collector config with `awsemf` + `awsxray` exporters)
- Create: `terraform/versions.tf` / per-module `versions.tf`, `terraform/environments/{dev,staging,prod}/` with `*.tfvars.example`, `backend.tf.example` (S3+DynamoDB lock placeholders — not live account IDs), `terraform/README.md`
- Modify: `Makefile` `tf-validate`; confirm `docs/ownership-raci.md` still accurate (ADR-008) — update only if module names drift
- Test: **commands** not inventory pytest — `make tf-validate`; optional checkov/tflint in CI Task 14

**Interfaces:**
- Consumes: naming from spec §5.4; FinOps tags `Project=doc-pipeline`, `Environment`, `CostCenter`, `Owner`
- Produces: modules that `terraform init -backend=false && terraform validate` per module or env
- IAM: **no** `Action = "*"` on task roles; api role cannot full-bucket `s3:GetObject` if worker owns reads; worker no broad `s3:PutObject` for client uploads
- ADOT module: separate YAML from Compose `infra/otel/collector.yaml`

**Spec:** §5.4–5.5, §8.4, §8.8, §9, Appendices A–C; ADR-006, ADR-007, ADR-010

**Acceptance:**
- `make tf-validate` exit 0
- Cost estimate note in root README (~$200–350 staging) labelled **estimate**
- No real `terraform apply`

**Steps:**

- [x] **Step 1:** Scaffold modules with variables/outputs; SQS module includes DLQ + redrive `maxReceiveCount=5`
- [x] **Step 2:** Run:

```bash
make tf-validate
```

Expected: `Success! The configuration is valid.` (per module loop)

- [x] **Step 3:** Add CloudWatch dashboard JSON + five alarms from Appendix B
- [x] **Step 4:** ADOT module documents EMF + X-Ray exporters; apps still only OTLP

---

### Task 14: Grafana/Prom rules + EN runbooks + CI workflows

**Files:**
- Create/expand: `docs/runbooks/dlq-replay.md`, `incident-queue-backlog.md`, `stuck-jobs.md`, `presign-expired.md`, `iam-access-denied.md`, `otel-export-fail.md`, `docs/slo.md`, `docs/architecture.md` (C4 summary from spec §4; LocalStack vs AWS), `docs/grafana/dashboards/*.json` panels for throughput/DLQ/age
- Create: `.github/workflows/integration.yml`, `terraform-plan.yml`, `terraform-apply-staging.yml`, `terraform-apply-prod.yml` (stubs: OIDC comments; **do not** configure real secrets; apply workflows `workflow_dispatch` only)
- Modify: `ci.yml` (ruff, mypy, unit, docker build); `infra/prometheus/alerts.yml`; README operator demo pointer (live `/v1/docs` + Grafana/Jaeger)
- Test: `tests/unit/test_grafana_dashboard.py` (parse JSON: UID present, no Tempo datasource), `tests/unit/test_prometheus_alerts.py` (rule names / expr contain DLQ)

**Interfaces:**
- Consumes: metric names from `docs/slo.md`
- Produces: operator-ready local dashboards + EN runbooks; GHA stubs

**Spec:** §8.5, §10.4, §11.3, §13, Appendix B; from-zero §11

**Acceptance:**
- Runbooks EN only; no links to gitignored harness paths
- Alerts: DLQ > 0; oldest message age > 10m; API 5xx; (RDS/ECS as Prom substitutes where local)
- CI does not require real AWS account

**Steps:**

- [x] **Step 1:**

```python
# tests/unit/test_prometheus_alerts.py
from pathlib import Path

import yaml


def test_dlq_alert_present() -> None:
    data = yaml.safe_load(Path("infra/prometheus/alerts.yml").read_text(encoding="utf-8"))
    text = str(data).lower()
    assert "dlq" in text
```

```python
# tests/unit/test_grafana_dashboard.py
import json
from pathlib import Path


def test_overview_dashboard_has_uid_and_no_tempo() -> None:
    raw = Path("docs/grafana/dashboards/pipeline_overview.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data.get("uid")
    assert "tempo" not in raw.lower()
```

- [x] **Step 2:** Implement dashboards + runbooks + workflows → GREEN

---

### Task 15: Stage 1 evidence commands (do not write Done in tracked docs)

**Files:**
- Create: local SDD harness (gitignored): Stage 1 DoD evidence file (**gitignored** harness — not tracked)
- Modify: `docs/progress.md` with Task↔spec linkage rows only (no “Stage 1 Done”)
- Modify: `AGENTS.md` §10.2 — set plan path to `docs/plans/2026-04-11-stage1-implementation-plan.md` (replace any TBD wording)
- Test: none new — run verification commands and paste exit codes into evidence file

**Interfaces:**
- Consumes: all prior tasks
- Produces: evidence checklist mapping DoD §11.2 items that can be proven locally

**Spec:** §10.3, §11.2; from-zero §2.8, §12

**Acceptance:**
- Commands run (or explicitly marked BLOCKED with reason):

```bash
cp -n .env.example .env
uv sync
make compose-up
make migrate
make seed && make seed-prod-like
make ci
make export-openapi
make tf-validate
# manual: open http://localhost:8000/v1/docs
# manual: Grafana :3000, Jaeger :16686 showing api→worker when traffic sent
```

- Evidence file lists §10.3 scenarios 1–8 with pass/fail/blocked
- Tracked docs **must not** say “Stage 1 Done”
- Load 500 docs/h note: optional local k6/Locust script path may be stubbed; label results **local**, not contractual SLA — if not run, mark evidence item pending human

**Steps:**

- [x] **Step 1:** Run `make ci` and `make tf-validate`; record exit codes
- [x] **Step 2:** Write local SDD harness (gitignored): Stage 1 DoD evidence file with command outputs summary
- [x] **Step 3:** Update `docs/progress.md` linkage only
- [x] **Step 4:** Update `AGENTS.md` §10.2: plan path = `docs/plans/2026-04-11-stage1-implementation-plan.md`

---

## Self-review checklist (author)

1. **Spec coverage:** §3.3 Must mapped in table; §10.3 scenarios 1–8 mapped; Appendices A–C covered in Tasks 13–14.
2. **Placeholders:** no TBD / “similar to Task N” without repeating code; commit steps stripped.
3. **Type consistency:** package `doc_pipeline`; UUIDv7 `id`; routes under `/v1/...`; hooks named `VirusScanHook` / `OcrHook` / `ExtractHook`; SQS not Kafka; no dual-id.
4. **OpenAPI:** locked in Task 0; expanded in Tasks 7–9.
5. **Excluded Must-nots:** Cognito, Textract, ClamAV vendor, webhook HMAC, Celery bus, Vite UI, EKS, Kafka, dual-id, real AWS apply, git commits — absent as Stage 1 Must.

---

## Execution handoff

Plan saved to `docs/plans/2026-04-11-stage1-implementation-plan.md`.

**1. Subagent-Driven (recommended)** — fresh Implementer per task, separate Reviewer, Gates A–D; no commits.

**2. Inline Execution** — `superpowers:executing-plans` with checkpoints.

Orchestrator starts at Task 0 per `PROMPT_PHASE_0_BOOTSTRAP` / Stage 1 phase prompts after CREATE_S1 is marked EXECUTED.

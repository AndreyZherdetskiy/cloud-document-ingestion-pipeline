# Cloud Document Ingestion Pipeline — Stage 2 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
> Implementer ≠ Reviewer. **Do not git commit.** No real AWS `terraform apply`.
> Execute per [`AGENTS.md`](../../AGENTS.md) §10. Role prompts: [`docs/agentic/role-prompts/`](../agentic/role-prompts/).
> Before Task 0: Orchestrator must have `PROMPT_PHASE_7_SPLIT_WORKERS.md` in local SDD harness (gitignored) ready (CREATE_S2 Next).
> Steps use checkbox (`- [ ]`) syntax for tracking.
> **Docker may be unavailable** in this WSL — prefer unit / moto / `terraform validate` first; mark live Compose/LocalStack tests `@pytest.mark.integration`.

**Goal:** Scale the Stage 1 MVP into Stage 2: split `ingestion-worker` / `processing-worker` (same package `doc_pipeline`, still SQS not Kafka), stuck-job scanner, outbound webhooks with HMAC, JWT stub + Cognito-swap ADR, real-ish hook adapters behind existing interfaces, ECS queue-depth autoscaling + secret-rotation docs, optional UI deferral, Stage 2 evidence (no Done label).

**Architecture:** Keep one Python package `src/doc_pipeline/`. S3 ObjectCreated still lands on the **ingestion** SQS queue; the ingestion worker validates/MIME/queues and publishes internal `PROCESS_DOCUMENT` messages to a **processing** SQS queue (+ DLQ). Processing worker runs Virus/OCR/Extract hooks and commits status+audit in one PostgreSQL transaction, then fires outbound webhooks. Auth stays JWT RS256 stub with a swap path documented for Cognito. Terraform modules gain dual worker services + autoscaling; never applied to a real account. Files never stream through the API.

**Tech Stack (as of plan date 2026-04-23):** Python 3.12.x; uv; FastAPI 0.115.x; Pydantic v2; SQLAlchemy 2 async; boto3; redis-py; PyJWT; uuid6; tenacity; OpenTelemetry OTLP; pytest ≥8,<9 + moto 5.x; Terraform 1.9.x + AWS provider 5.x. Optional Celery **not** required — asyncio periodic scanner is the default stuck-job path. Optional Vite UI deferred (Task 6). **Current product floor:** `spec.md` §5 (e.g. FastAPI 0.141.x, redis-py 8.1.x, LocalStack 4.14.x).

## Global Constraints

Copy from `PROMPT_COMMON.md` §5 / `AGENTS.md` §2 (every task implicitly includes these):

1. **Control / data plane split** — API never proxies file bytes (ADR-004). Presign PUT to S3.
2. **S3 → SQS → worker**, not S3 → Lambda (ADR-001). **No Kafka.** Work queue = SQS Standard + DLQ (`maxReceiveCount=5`). Celery optional for stuck-job scanner only — not the ingestion bus.
3. **At-least-once** + Redis `SET NX` + status checks. No exactly-once (ADR-002).
4. **Status + audit in one PostgreSQL transaction.** `audit_log` append-only; app must not UPDATE/DELETE it (ADR-003).
5. **Hook interfaces** (`VirusScanHook`, `OcrHook`, `ExtractHook`) — stubs default; Stage 2 adapters plug in (ADR-005).
6. **Compute target AWS:** ECS Fargate (ADR-006). Local: Compose `api` + `ingestion-worker` + `processing-worker`. K8s/EKS not Must.
7. **Terraform + OIDC is the only infra change path** (ADR-007). Write modules; do not apply to real AWS.
8. **RACI** in `docs/ownership-raci.md` (ADR-008). App never “fixes” bucket policy at runtime.
9. **Stage 1 demo does not require UI** (ADR-009). Optional thin UI is Stage 2+ and **not a Stage 2 gate**.
10. **Secrets:** local `.env` / Settings; AWS path SSM + Secrets Manager (ADR-010) — rotation docs only; not applied unless human GO.
11. **No RDS sharding Stages 1–3.** Writes only on primary (ADR-011).
12. **UUIDv7 PK everywhere; no dual-id; no composite `(tenant_id, id)` PK** (ADR-012).
13. **Tenant isolation:** every query filtered by `tenant_id` from JWT. Foreign ID → **404**, not 403.
14. **Poison:** after `maxReceiveCount=5` → DLQ; worker deletes SQS message only on success **or after recording terminal FAILED**.
15. **Auth:** JWT RS256 stub remains default; Cognito documented as swap (this environment has **no real AWS**).
16. **Pagination:** cursor + `limit` (default 50, max 200). Do not invent `offset`.
17. **Correlation:** `X-Correlation-ID` / `X-Correlation-Id`; UUIDv7; invalid → **422**; never log full presigned URLs.
18. **OpenAPI bar** (from-zero §2.1): live `/v1/docs`; summary+description; Field/Header descriptions; `responses=` for raised codes; no `spec.md`/ADR in OpenAPI prose.
19. **Observability:** Apps export **only OTLP**. Local Jaeger; AWS ADOT → CloudWatch EMF + X-Ray (already in `terraform/modules/adot/`). Metric attrs: `tenant_slug`, `document_type`, `status`, `hook` — never `document_id` / `correlation_id`.
20. **Quality:** Python 3.12; pytest **8**; `--import-mode=importlib --strict-markers`; behavioral tests only.
21. **Images:** non-root USER; no `COPY .env`.
22. **Do not declare Stage Done.** Evidence: local SDD harness (gitignored): Stage 2 DoD evidence file.
23. **Anti-copy:** no Hub dual-id/Kafka/HMAC-as-bus; no billing ledger; no EKS-as-Must; no Textract-as-Must (adapter interface only).
24. **No git commit / push / gh / real AWS apply** without explicit human command.
25. **Imports at module top.** No `Task N` left in application code after a task ships.
26. **Frozen ports:** api 8000, postgres 5432, redis 6379, localstack 4566, OTLP 4317/4318, prometheus 9090, grafana 3000, jaeger 16686, optional UI 8080. Workers have no public host port.
27. **Settings** from `.env` only (`env_file=".env"`, `extra="ignore"`). Empty `OTEL_SDK_DISABLED=` must not crash bool parse.
28. **Webhook secrets** never in git — Settings / Secrets Manager path only.

**Stage 2 Must NOT include:** EKS, Kafka, dual-id, multi-region AA, Object Lock, real `terraform apply`, git commit, Textract-as-Must, live Cognito against a real AWS account, Celery as the work bus, full operator portal.

---

## File map (Stage 2)

| Path | Responsibility |
|------|----------------|
| `src/doc_pipeline/worker/events.py` | Extend with `ProcessDocumentMessage` parse/serialize (§7.5) |
| `src/doc_pipeline/worker/ingestion_handlers.py` | S3 ingest → QUEUED + enqueue PROCESS_DOCUMENT |
| `src/doc_pipeline/worker/processing_handlers.py` | PROCESS_DOCUMENT → hooks → terminal + webhook hook point |
| `src/doc_pipeline/worker/ingestion_consumer.py` | Long-poll ingestion queue |
| `src/doc_pipeline/worker/processing_consumer.py` | Long-poll processing queue |
| `src/doc_pipeline/worker/ingestion_main.py` / `processing_main.py` | Entrypoints (`python -m …`) |
| `src/doc_pipeline/worker/stuck_scanner.py` | Asyncio periodic STUCK marker |
| `src/doc_pipeline/domain/services/webhook_service.py` | HMAC sign, deliver, retry |
| `src/doc_pipeline/api/auth/token_verifier.py` | `TokenVerifier` Protocol + stub |
| `src/doc_pipeline/domain/hooks/adapters/` | Real-ish virus/OCR adapters; stubs stay default |
| `docs/adr/013-cognito-swap-jwt-stub.md` | Cognito swap without live AWS |
| `docs/runbooks/secret-rotation.md` | Secrets Manager rotation ops |
| `docs/plans/stage2-ui-deferral.md` | Optional UI deferral note (ADR-009 / §13) |
| `terraform/modules/sqs/` | Add processing queue + DLQ |
| `terraform/modules/ecs/` | Split worker services + autoscaling |
| `docker-compose.yml` | `ingestion-worker` + `processing-worker` (when Docker exists) |
| `.env.example` | New Settings keys (processing queue, webhooks, hook backend, stuck threshold) |

---

## Spec §3.4 → tasks

| §3.4 bullet | Task(s) |
|-------------|--------|
| Split `ingestion-worker` / `processing-worker` (ECS / Compose) | 0 |
| Native SQS long-poll; Celery optional for stuck only | 0, 1 |
| Webhooks `document.processed` / `document.failed` + signature + retries | 2 |
| Cognito / OAuth2 client credentials | 3 (JWT stub + ADR swap; M2M client credentials deferred; no live Cognito) |
| Real virus-scan; Textract/OCR behind same interface | 4 |
| X-Ray / OpenTelemetry | 5 (ADOT `awsxray` already present — verify/document) |
| ECS autoscaling on `ApproximateNumberOfMessagesVisible` | 5 |
| Staging + prod; manual prod apply approval | 5 (docs / TF envs; no apply) |
| Secret rotation in Secrets Manager | 5 (runbook) |
| Optional thin Vite UI (§13) | 6 (deferral note; not a gate) |
| Stage 2 evidence (no Done) | 7 |

---

### Task 0: Split ingestion vs processing workers (unit/moto first)

**Files:**
- Create: `src/doc_pipeline/worker/ingestion_handlers.py`, `src/doc_pipeline/worker/processing_handlers.py`, `src/doc_pipeline/worker/ingestion_consumer.py`, `src/doc_pipeline/worker/processing_consumer.py`, `src/doc_pipeline/worker/ingestion_main.py`, `src/doc_pipeline/worker/processing_main.py`, `tests/unit/worker/test_process_document_message.py`, `tests/unit/worker/test_ingestion_enqueue.py`, `tests/unit/worker/test_processing_hooks_path.py`
- Modify: `src/doc_pipeline/worker/events.py`, `src/doc_pipeline/worker/handlers.py` (thin re-export or deprecate single-path in favor of split), `src/doc_pipeline/config/settings.py`, `.env.example`, `terraform/modules/sqs/main.tf`, `terraform/modules/sqs/outputs.tf`, `terraform/modules/sqs/variables.tf`, `terraform/modules/ecs/main.tf`, `terraform/modules/ecs/variables.tf`, `terraform/modules/ecs/outputs.tf`, `docker-compose.yml` (split services; skip live if no Docker), `deploy/Dockerfile.worker` (same image, different CMD/module), `Makefile` (targets for both workers if present)
- Test: `tests/unit/worker/test_process_document_message.py`, `tests/unit/worker/test_ingestion_enqueue.py`, `tests/unit/worker/test_processing_hooks_path.py`
- Integration (optional, marked): `tests/integration/test_worker_split_queues.py` with `@pytest.mark.integration`

**Interfaces:**
- Consumes:
  - `parse_s3_event_message(body: str) -> S3IngestEvent` (Stage 1)
  - `VirusScanHook` / `OcrHook` / `ExtractHook` + stubs
  - `acquire_processing_lock` / Redis `SET NX` (ADR-002)
  - `transition(...)` state machine
- Produces:
  - `@dataclass(frozen=True) ProcessDocumentMessage` with fields: `schema_version: str`, `message_type: Literal["PROCESS_DOCUMENT"]`, `job_id: UUID`, `document_id: UUID`, `tenant_id: UUID`, `document_type: DocumentType`, `s3_bucket: str`, `s3_key: str`, `attempt: int`, `correlation_id: UUID`, `requested_hooks: tuple[str, ...]`
  - `serialize_process_document_message(msg: ProcessDocumentMessage) -> str`
  - `parse_process_document_message(body: str) -> ProcessDocumentMessage`
  - `async def handle_ingestion_event(*, session, settings, redis, sqs_client, body: str, hooks_unused=None) -> DocumentStatus` — MIME/validate → `QUEUED` + send PROCESS_DOCUMENT; terminal MIME fail → `FAILED` + delete ingest receipt path unchanged from Stage 1 semantics
  - `async def handle_processing_message(*, session, settings, redis, hooks: tuple[VirusScanHook, OcrHook, ExtractHook], body: str) -> DocumentStatus` — hooks → `PROCESSED` | `FAILED`
  - Settings: `sqs_processing_queue_url: str`, `sqs_processing_dlq_url: str`
  - Compose services: `ingestion-worker`, `processing-worker` (no host ports)
  - Terraform: `aws_sqs_queue.processing`, `aws_sqs_queue.processing_dlq`, ECS services `ingestion-worker` / `processing-worker`

**Spec:** §3.4, §7.4–7.5, §4.3–4.4; ADR-001, ADR-002, ADR-006

**Acceptance:**
- Unit tests prove PROCESS_DOCUMENT round-trip and that ingestion enqueues exactly one processing message after successful MIME path
- Processing path still commits status+audit in one transaction; stubs remain default hooks
- Duplicate PROCESS_DOCUMENT → single `PROCESSED` (Redis NX + status checks)
- `terraform validate` green after SQS/ECS split resources added
- No Kafka; no file bytes through API
- Live Compose split marked integration-only if Docker unavailable

**Steps:**

- [ ] **Step 1: Write failing PROCESS_DOCUMENT contract tests**

```python
# tests/unit/worker/test_process_document_message.py
import json
from uuid import UUID

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.worker.events import (
    ProcessDocumentMessage,
    parse_process_document_message,
    serialize_process_document_message,
)


def test_process_document_round_trip() -> None:
    msg = ProcessDocumentMessage(
        schema_version="1",
        message_type="PROCESS_DOCUMENT",
        job_id=generate_uuidv7(),
        document_id=generate_uuidv7(),
        tenant_id=generate_uuidv7(),
        document_type=DocumentType.INVOICE,
        s3_bucket="dev-doc-pipeline",
        s3_key="t/d/file.pdf",
        attempt=1,
        correlation_id=generate_uuidv7(),
        requested_hooks=("virus", "ocr", "extract"),
    )
    raw = serialize_process_document_message(msg)
    parsed = parse_process_document_message(raw)
    assert parsed.message_type == "PROCESS_DOCUMENT"
    assert parsed.document_id == msg.document_id
    assert parsed.document_type == DocumentType.INVOICE
    assert "virus" in parsed.requested_hooks
    body = json.loads(raw)
    assert body["message_type"] == "PROCESS_DOCUMENT"
    UUID(str(body["correlation_id"]))
```

```python
# tests/unit/worker/test_ingestion_enqueue.py
"""Ingestion worker enqueues exactly one PROCESS_DOCUMENT after MIME-OK path."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.worker.events import parse_process_document_message, parse_s3_event_message
from doc_pipeline.worker.ingestion_handlers import handle_ingestion_event
from tests.unit.test_worker_handler import FakeWorkerSession, event_for


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        aws_region="eu-central-1",
        s3_bucket="dev-doc-pipeline",
        sqs_queue_url="http://localhost/ingest",
        sqs_dlq_url="http://localhost/ingest-dlq",
        sqs_processing_queue_url="http://localhost/processing",
        sqs_processing_dlq_url="http://localhost/processing-dlq",
        jwt_public_key_pem="-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
        otel_sdk_disabled=True,
    )


@pytest.mark.asyncio
async def test_ingestion_enqueues_process_document_red() -> None:
    """RED: module/handler missing — delete this test once GREEN below passes."""
    sqs = MagicMock()
    settings = _settings()
    with pytest.raises((ImportError, AttributeError, TypeError, NotImplementedError)):
        await handle_ingestion_event(
            session=None,  # type: ignore[arg-type]
            settings=settings,
            redis=MagicMock(),
            sqs_client=sqs,
            body='{"Records":[]}',
        )


@pytest.mark.asyncio
async def test_ingestion_enqueues_process_document_green() -> None:
    """GREEN: exactly one send_message to processing queue; body is PROCESS_DOCUMENT."""
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    document = Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.UPLOADED.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
        file_name="invoice.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )
    tenant = Tenant(id=tenant_id, name="Acme", slug="acme", config_json={})
    session = FakeWorkerSession(document, tenant)
    settings = _settings()
    sqs = MagicMock()
    sqs.send_message.return_value = {"MessageId": "m-1"}
    body = json.dumps(event_for(document))

    status = await handle_ingestion_event(
        session=session,  # type: ignore[arg-type]
        settings=settings,
        redis=MagicMock(),
        sqs_client=sqs,
        body=body,
    )

    assert status is DocumentStatus.QUEUED
    sqs.send_message.assert_called_once()
    call_kwargs = sqs.send_message.call_args.kwargs
    assert call_kwargs["QueueUrl"] == settings.sqs_processing_queue_url
    parsed = parse_process_document_message(call_kwargs["MessageBody"])
    assert parsed.message_type == "PROCESS_DOCUMENT"
    assert parsed.document_id == doc_id
    assert parsed.tenant_id == tenant_id
    assert parsed.s3_bucket == document.s3_bucket
    assert parsed.s3_key == document.s3_key
    # Sanity: ingest envelope still parses (handler used it).
    assert parse_s3_event_message(json.loads(body)).document_id == doc_id
```

```python
# tests/unit/worker/test_processing_hooks_path.py
"""Processing worker: hooks → PROCESSED/FAILED; duplicate PROCESS_DOCUMENT → hooks once."""
from __future__ import annotations

import pytest

from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.enums import DocumentStatus, DocumentType
from doc_pipeline.domain.hooks.stubs import StubExtractHook, StubOcrHook, StubVirusScanHook
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.models.document import Document
from doc_pipeline.domain.models.tenant import Tenant
from doc_pipeline.infrastructure.cache.redis import InMemoryRedisCache
from doc_pipeline.worker.events import ProcessDocumentMessage, serialize_process_document_message
from doc_pipeline.worker.processing_handlers import handle_processing_message
from tests.unit.test_worker_handler import FakeWorkerSession


def _process_body(document: Document) -> str:
    msg = ProcessDocumentMessage(
        schema_version="1",
        message_type="PROCESS_DOCUMENT",
        job_id=generate_uuidv7(),
        document_id=document.id,
        tenant_id=document.tenant_id,
        document_type=DocumentType(document.document_type),
        s3_bucket=document.s3_bucket or "dev-doc-pipeline",
        s3_key=document.s3_key or "k",
        attempt=1,
        correlation_id=generate_uuidv7(),
        requested_hooks=("virus", "ocr", "extract"),
    )
    return serialize_process_document_message(msg)


@pytest.fixture
def queued_document() -> Document:
    tenant_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    return Document(
        id=doc_id,
        tenant_id=tenant_id,
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.QUEUED.value,
        idempotency_key=f"idem-{doc_id}",
        s3_bucket="dev-doc-pipeline",
        s3_key=f"{tenant_id}/{doc_id}/invoice.pdf",
        file_name="invoice.pdf",
        mime_type="application/pdf",
        checksum_sha256="a" * 64,
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(otel_sdk_disabled=True)


@pytest.fixture
def tenant_for(queued_document: Document) -> Tenant:
    return Tenant(id=queued_document.tenant_id, name="Acme", slug="acme", config_json={})


@pytest.fixture
def db_session(queued_document: Document, tenant_for: Tenant) -> FakeWorkerSession:
    return FakeWorkerSession(queued_document, tenant_for)


@pytest.fixture
def redis() -> InMemoryRedisCache:
    return InMemoryRedisCache()


@pytest.mark.asyncio
async def test_processing_happy_path_processed(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    status = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=_process_body(queued_document),
    )
    assert status is DocumentStatus.PROCESSED
    assert queued_document.status == DocumentStatus.PROCESSED.value
    assert queued_document.processing_result_json is not None
    assert db_session.commits >= 1


@pytest.mark.asyncio
async def test_processing_virus_fail_sets_failed(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
) -> None:
    hooks = (StubVirusScanHook(clean=False), StubOcrHook(), StubExtractHook())
    status = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=_process_body(queued_document),
    )
    assert status is DocumentStatus.FAILED
    assert queued_document.status == DocumentStatus.FAILED.value
    assert queued_document.failure_reason is not None


@pytest.mark.asyncio
async def test_duplicate_process_document_runs_hooks_once(
    db_session: FakeWorkerSession,
    queued_document: Document,
    settings: Settings,
    redis: InMemoryRedisCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks = (StubVirusScanHook(clean=True), StubOcrHook(), StubExtractHook())
    calls = {"n": 0}
    real_scan = hooks[0].scan

    async def counting_scan(ctx: object) -> object:
        calls["n"] += 1
        return await real_scan(ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(hooks[0], "scan", counting_scan)
    body = _process_body(queued_document)
    s1 = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=body,
    )
    s2 = await handle_processing_message(
        session=db_session,  # type: ignore[arg-type]
        settings=settings,
        redis=redis,
        hooks=hooks,
        body=body,
    )
    assert s1 is DocumentStatus.PROCESSED
    assert s2 is DocumentStatus.PROCESSED  # idempotent: already terminal
    assert calls["n"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/worker/test_process_document_message.py tests/unit/worker/test_ingestion_enqueue.py::test_ingestion_enqueues_process_document_red -v`

Expected: FAIL — `ProcessDocumentMessage` / `handle_ingestion_event` not found or incomplete. `test_processing_hooks_path.py` and `test_ingestion_enqueues_process_document_green` may also fail until Step 3.

- [ ] **Step 3: Implement message types + ingestion enqueue + processing handler**

Minimal shape (implementer expands with real DB/session wiring matching Stage 1 `handlers.py`):

```python
# src/doc_pipeline/worker/events.py (additions)
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from doc_pipeline.domain.enums import DocumentType


@dataclass(frozen=True)
class ProcessDocumentMessage:
    schema_version: str
    message_type: Literal["PROCESS_DOCUMENT"]
    job_id: UUID
    document_id: UUID
    tenant_id: UUID
    document_type: DocumentType
    s3_bucket: str
    s3_key: str
    attempt: int
    correlation_id: UUID
    requested_hooks: tuple[str, ...]


def serialize_process_document_message(msg: ProcessDocumentMessage) -> str: ...
def parse_process_document_message(body: str) -> ProcessDocumentMessage: ...
```

```python
# ingestion: after MIME OK → transition to QUEUED, create/update Job RUNNING/PENDING,
# sqs_client.send_message(QueueUrl=settings.sqs_processing_queue_url, MessageBody=serialize_...)
# processing: parse_process_document_message → virus/ocr/extract → PROCESSED|FAILED + audit txn
```

Remove `test_ingestion_enqueues_process_document_red` once GREEN passes. Reuse `FakeWorkerSession` / `event_for` from `tests/unit/test_worker_handler.py`.

Terraform: add `aws_sqs_queue.processing` + `processing_dlq` with `maxReceiveCount=5`; replace single `aws_ecs_service.worker` with `ingestion-worker` and `processing-worker` task defs/services (same image, different command: `python -m doc_pipeline.worker.ingestion_main` vs `processing_main`).

Compose: rename/split `worker` into two services sharing `deploy/Dockerfile.worker`.

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `uv run pytest tests/unit/worker/test_process_document_message.py tests/unit/worker/test_ingestion_enqueue.py tests/unit/worker/test_processing_hooks_path.py -v`

Expected: PASS — enqueue asserts exactly one `send_message` to `settings.sqs_processing_queue_url` with `PROCESS_DOCUMENT` body; processing path covers PROCESSED, virus FAILED, duplicate → hooks once.

- [ ] **Step 5: Validate Terraform (no apply)**

Run: `make tf-validate`

Expected: PASS (exit 0)

- [ ] **Step 6: Integration (only if Docker available)**

Run: `uv run pytest tests/integration/test_worker_split_queues.py -v -m integration`

Expected: PASS when LocalStack+Compose up; otherwise skip/xfail with clear reason — do not block Task 0.

---

### Task 1: Stuck-job scanner (asyncio periodic)

**Files:**
- Create: `src/doc_pipeline/worker/stuck_scanner.py`, `src/doc_pipeline/worker/stuck_main.py`, `tests/unit/worker/test_stuck_scanner.py`
- Modify: `src/doc_pipeline/config/settings.py`, `.env.example`, `docs/runbooks/stuck-jobs.md` (point to scanner), `docker-compose.yml` (optional `stuck-scanner` service or flag on processing-worker — prefer side loop started from `stuck_main` / shared process; document choice)
- Test: `tests/unit/worker/test_stuck_scanner.py`

**Interfaces:**
- Consumes: `Job` model (`status`, `started_at` / `created_at`), `JobStatus.STUCK`, `JobStatus.RUNNING` / `PENDING`
- Produces:
  - `async def mark_stuck_jobs(*, session: AsyncSession, older_than: timedelta, now: datetime | None = None) -> int` — returns count marked
  - `async def run_stuck_scanner_loop(*, sessionmaker, settings, stop_event: asyncio.Event) -> None` — sleep `stuck_scan_interval_seconds`, call `mark_stuck_jobs`
  - Settings: `stuck_job_older_than_seconds: int` (default `1800`), `stuck_scan_interval_seconds: int` (default `60`)
  - Does **not** replace SQS; does **not** require Celery (asyncio OK per Stage 2 Must)

**Spec:** §3.4, §2.3 J-02 (`GET /v1/jobs?status=STUCK&older_than=…`), §8.2; ADR-002

**Acceptance:**
- Jobs in `RUNNING` (or non-terminal mid-flight) older than threshold become `STUCK`
- Already terminal jobs unchanged
- Scanner idempotent: already `STUCK` not double-audited incorrectly (either no-op or single transition rule — document)
- Unit tests use freezegun or injected `now`; no Docker required
- Celery **not** introduced unless Implementer files a short ADR exception (default = asyncio)

**Steps:**

- [ ] **Step 1: Write failing stuck-scanner tests**

```python
# tests/unit/worker/test_stuck_scanner.py
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from doc_pipeline.domain.enums import JobStatus
from doc_pipeline.worker.stuck_scanner import mark_stuck_jobs


class _FakeJob:
    def __init__(self, status: str, started_at: datetime) -> None:
        self.id = uuid4()
        self.status = status
        self.started_at = started_at


class _FakeSession:
    def __init__(self, jobs: list[_FakeJob]) -> None:
        self.jobs = jobs
        self.committed = False

    async def execute(self, *_a, **_k):  # implementer adapts to real SQLAlchemy Result
        raise NotImplementedError

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_mark_stuck_jobs_updates_old_running() -> None:
    now = datetime(2026, 4, 23, 12, 0, tzinfo=UTC)
    old = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=45))
    fresh = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=5))
    done = _FakeJob(JobStatus.SUCCEEDED, now - timedelta(hours=2))
    # RED: mark_stuck_jobs must exist and mark only `old`
    session = object()  # replace with real AsyncSession / in-memory repo in GREEN
    with pytest.raises((ImportError, AttributeError, TypeError, NotImplementedError)):
        n = await mark_stuck_jobs(
            session=session,  # type: ignore[arg-type]
            older_than=timedelta(minutes=30),
            now=now,
        )
        assert n == 1
        assert old.status == JobStatus.STUCK
        assert fresh.status == JobStatus.RUNNING
        assert done.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_mark_stuck_jobs_green() -> None:
    """GREEN: replace _FakeSession.execute with real SQLAlchemy or in-memory repo."""
    now = datetime(2026, 4, 23, 12, 0, tzinfo=UTC)
    old = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=45))
    fresh = _FakeJob(JobStatus.RUNNING, now - timedelta(minutes=5))
    done = _FakeJob(JobStatus.SUCCEEDED, now - timedelta(hours=2))
    already = _FakeJob(JobStatus.STUCK, now - timedelta(hours=1))
    session = _FakeSession([old, fresh, done, already])
    # Implementer: wire session.execute to return jobs matching select(Job) filter.
    n = await mark_stuck_jobs(
        session=session,  # type: ignore[arg-type]
        older_than=timedelta(minutes=30),
        now=now,
    )
    assert n == 1
    assert old.status == JobStatus.STUCK
    assert fresh.status == JobStatus.RUNNING
    assert done.status == JobStatus.SUCCEEDED
    assert already.status == JobStatus.STUCK  # unchanged
    assert session.committed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/worker/test_stuck_scanner.py::test_mark_stuck_jobs_updates_old_running -v`

Expected: FAIL — `mark_stuck_jobs` missing or `NotImplementedError`.

- [ ] **Step 3: Implement scanner**

```python
# src/doc_pipeline/worker/stuck_scanner.py
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from doc_pipeline.domain.enums import JobStatus
from doc_pipeline.domain.models.job import Job


async def mark_stuck_jobs(
    *,
    session: AsyncSession,
    older_than: timedelta,
    now: datetime | None = None,
) -> int:
    ts = now or datetime.now(UTC)
    cutoff = ts - older_than
    result = await session.execute(
        select(Job).where(
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            Job.started_at.is_not(None),
            Job.started_at < cutoff,
        )
    )
    jobs = list(result.scalars())
    for job in jobs:
        job.status = JobStatus.STUCK
    await session.commit()
    return len(jobs)
```

Wire `stuck_main` loop with `asyncio.sleep(settings.stuck_scan_interval_seconds)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/worker/test_stuck_scanner.py -v`

Expected: PASS — `test_mark_stuck_jobs_green` asserts count=1, only old RUNNING → STUCK, terminal/STUCK unchanged.

- [ ] **Step 5: Update stuck-jobs runbook**

One paragraph in `docs/runbooks/stuck-jobs.md`: scanner marks `STUCK`; operators still use `POST /v1/jobs/{id}/retry` — no manual SQL.

---

### Task 2: Outbound webhooks (HMAC + retries + OpenAPI note)

**Files:**
- Create: `src/doc_pipeline/domain/services/webhook_service.py`, `tests/unit/services/test_webhook_hmac.py`, `tests/unit/services/test_webhook_delivery.py`
- Modify: `src/doc_pipeline/worker/processing_handlers.py` (call after terminal PROCESSED/FAILED), `src/doc_pipeline/config/settings.py`, `.env.example`, `tests/unit/test_openapi_docs.py` (tag/description if any webhook admin endpoints added — Stage 2 may be outbound-only with tenant `config_json` URL; if no HTTP CRUD, document in OpenAPI info description one sentence that clients receive signed webhooks)
- Test: `tests/unit/services/test_webhook_hmac.py`, `tests/unit/services/test_webhook_delivery.py`

**Interfaces:**
- Consumes: terminal document status, tenant webhook URL + secret from Settings or `tenants.config_json` keys `webhook_url` / `webhook_secret` (prefer tenant config with Settings fallback for demo)
- Produces:
  - `def sign_webhook_body(*, secret: str, body: bytes) -> str` → header value `sha256=<hex>`
  - `def build_webhook_payload(*, event_type: Literal["document.processed","document.failed"], event_id: UUID, occurred_at: datetime, tenant_id: UUID, document_id: UUID, status: str, external_ref: str | None, processing_result: dict | None) -> dict`
  - `async def deliver_webhook(*, http_client, url: str, secret: str, payload: dict, max_attempts: int = 3, skip: bool = False) -> None` — retries with tenacity on 5xx/timeout; when `skip=True` (status already terminal before commit), no HTTP; **does not** raise into SQS retry after terminal commit (log + metric on exhaust; ADR-002: webhook is side effect after durable status)
  - Header: `X-Webhook-Signature`
  - Settings: `webhook_timeout_seconds: float = 5.0`, `webhook_max_attempts: int = 3`, optional global `webhook_default_secret` for local demo only (placeholder in `.env.example`)

**Spec:** §3.4, §7.7

**Acceptance:**
- Events exactly `document.processed` and `document.failed`
- Signature = HMAC-SHA256 over raw JSON body; header `X-Webhook-Signature: sha256=<hex>`
- Payload fields: `event_id`, `event_type`, `occurred_at`, `tenant_id`, `data` with `document_id`, `status`, `external_ref`, `processing_result`
- Secret never committed; `.env.example` placeholder only
- Unit tests with `httpx.MockTransport` or `respx`; no live network
- Duplicate processing must not double-fire if status already terminal (idempotent guard)

**Steps:**

- [ ] **Step 1: Write failing HMAC + delivery tests**

```python
# tests/unit/services/test_webhook_hmac.py
import hashlib
import hmac
import json
from datetime import UTC, datetime

from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.services.webhook_service import (
    build_webhook_payload,
    sign_webhook_body,
)


def test_sign_webhook_body_sha256_hex() -> None:
    secret = "test-secret"
    body = b'{"event_type":"document.processed"}'
    sig = sign_webhook_body(secret=secret, body=body)
    assert sig.startswith("sha256=")
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={digest}"


def test_build_webhook_payload_shape() -> None:
    eid = generate_uuidv7()
    tid = generate_uuidv7()
    did = generate_uuidv7()
    payload = build_webhook_payload(
        event_type="document.processed",
        event_id=eid,
        occurred_at=datetime(2026, 4, 23, 12, 0, tzinfo=UTC),
        tenant_id=tid,
        document_id=did,
        status="PROCESSED",
        external_ref="EXT-1",
        processing_result={"pages": 1},
    )
    assert payload["event_type"] == "document.processed"
    assert payload["event_id"] == str(eid)
    assert payload["tenant_id"] == str(tid)
    assert payload["data"]["document_id"] == str(did)
    assert payload["data"]["status"] == "PROCESSED"
    json.dumps(payload)  # serializable
```

```python
# tests/unit/services/test_webhook_delivery.py
import httpx
import pytest

from doc_pipeline.domain.services.webhook_service import deliver_webhook


@pytest.mark.asyncio
async def test_deliver_webhook_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, request=request)
        assert request.headers.get("X-Webhook-Signature", "").startswith("sha256=")
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await deliver_webhook(
            http_client=client,
            url="https://example.test/hooks",
            secret="s",
            payload={"event_type": "document.failed", "data": {}},
            max_attempts=3,
        )
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_deliver_webhook_skips_when_already_terminal() -> None:
    """Idempotent guard: no HTTP when document already PROCESSED/FAILED (caller passes flag)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await deliver_webhook(
            http_client=client,
            url="https://example.test/hooks",
            secret="s",
            payload={"event_type": "document.processed", "data": {}},
            max_attempts=3,
            skip=True,  # implementer: skip=True when status already terminal
        )
    assert calls["n"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/services/test_webhook_hmac.py tests/unit/services/test_webhook_delivery.py -v`

Expected: FAIL — module/functions missing.

- [ ] **Step 3: Implement webhook_service + wire processing handler**

After successful terminal commit for `PROCESSED`/`FAILED`, call `deliver_webhook`. Failures of webhook after durable status must not re-raise to leave SQS message undeleted.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/services/test_webhook_hmac.py tests/unit/services/test_webhook_delivery.py -v`

Expected: PASS

- [ ] **Step 5: OpenAPI / Settings**

Extend `.env.example` with `WEBHOOK_*` placeholders. If OpenAPI info description mentions webhooks, keep prose free of `spec.md`/ADR citations. Re-run:

Run: `uv run pytest tests/unit/test_openapi_docs.py -v`

Expected: PASS

---

### Task 3: Auth — JWT stub + Cognito swap ADR (no live Cognito)

**Files:**
- Create: `src/doc_pipeline/api/auth/__init__.py`, `src/doc_pipeline/api/auth/token_verifier.py`, `docs/adr/013-cognito-swap-jwt-stub.md`, `tests/unit/auth/test_token_verifier_stub.py`
- Modify: `src/doc_pipeline/api/deps.py` (delegate decode to `TokenVerifier`), `src/doc_pipeline/config/settings.py` (`auth_backend: Literal["stub","cognito"] = "stub"`, optional `cognito_jwks_url` unused when stub), `.env.example`, `AGENTS.md` §2 auth bullet / §10 Stage 2 pointer if needed
- Test: `tests/unit/auth/test_token_verifier_stub.py`

**Interfaces:**
- Consumes: existing `Principal(sub, tenant_id, roles)`, Settings JWT fields
- Produces:
  - `class TokenVerifier(Protocol): def verify(self, token: str) -> Principal: ...`
  - `class StubJwtVerifier: def __init__(self, settings: Settings) -> None: ...` / `def verify(self, token: str) -> Principal`
  - `class CognitoJwtVerifier:` — JWKS-based skeleton that raises `NotImplementedError("Cognito requires AWS account; use auth_backend=stub")` **or** implements JWKS verify behind feature flag but **never** called in default CI (prefer stub path; skeleton documents claims mapping `sub`/`custom:tenant_id`/`cognito:groups` → `Principal`)
  - `def get_token_verifier(settings: Settings) -> TokenVerifier`
  - ADR-013: Context (no real AWS here), Decision (keep stub default; Cognito is drop-in `TokenVerifier`), **OAuth2 client credentials (M2M) deferred** to live Cognito phase — Stage 2 stub JWT covers dev/service tokens; Consequences, Alternatives

**Spec:** §3.4 Cognito bullet; §2.2; §7.1; ADR-009 N/A; Stage 2 from-zero §12

**Acceptance:**
- Default `AUTH_BACKEND=stub` — all existing JWT unit tests still pass
- `get_current_principal` uses `TokenVerifier.verify`
- ADR-013 Accepted; states no live Cognito apply in this environment
- ADR-013 explicitly defers **OAuth2 client credentials (M2M)** to live Cognito; Stage 2 `auth_backend=stub` JWT covers dev/service tokens (no separate client-credentials flow in Stage 2)
- No AWS Cognito User Pool Terraform apply; optional TF skeleton deferred (document in ADR as future module — do not require live resources)
- OpenAPI Authorization header description may say “Bearer JWT (RS256); stub issuer locally, Cognito-compatible claims”

**Steps:**

- [ ] **Step 1: Write failing TokenVerifier tests**

```python
# tests/unit/auth/test_token_verifier_stub.py
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from doc_pipeline.api.auth.token_verifier import StubJwtVerifier, get_token_verifier
from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.ids import generate_uuidv7


def _rsa_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def test_stub_verifier_returns_principal() -> None:
    private_pem, public_pem = _rsa_pair()
    tenant_id = generate_uuidv7()
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        aws_region="eu-central-1",
        s3_bucket="b",
        sqs_queue_url="http://localhost/q",
        sqs_dlq_url="http://localhost/dlq",
        jwt_issuer="http://localhost:8000/dev-issuer",
        jwt_audience="doc-pipeline",
        jwt_public_key_pem=public_pem,
        auth_backend="stub",
    )
    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": str(tenant_id),
            "roles": ["ROLE_OPERATOR"],
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        private_pem,
        algorithm="RS256",
    )
    verifier = get_token_verifier(settings)
    assert isinstance(verifier, StubJwtVerifier)
    principal = verifier.verify(token)
    assert principal.sub == "user-1"
    assert principal.tenant_id == tenant_id
    assert "ROLE_OPERATOR" in principal.roles
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/auth/test_token_verifier_stub.py -v`

Expected: FAIL — `token_verifier` / `auth_backend` missing.

- [ ] **Step 3: Implement Protocol + stub + ADR-013; wire deps**

Write `docs/adr/013-cognito-swap-jwt-stub.md` (Accepted). Required sections:

- **Context:** No real AWS Cognito in this environment.
- **Decision:** Default `auth_backend=stub`; `TokenVerifier` Protocol allows drop-in `CognitoJwtVerifier`.
- **OAuth2 client credentials:** M2M client-credentials flow **deferred** to live Cognito phase (User Pool app client + hosted domain). Stage 2 stub JWT covers dev and service tokens; no separate token endpoint in Stage 2.
- **Consequences / Alternatives:** Document JWKS swap path; no Cognito Terraform apply.

Refactor `get_current_principal` to call `get_token_verifier(settings).verify(token)`.

- [ ] **Step 4: Run auth + existing JWT API tests**

Run: `uv run pytest tests/unit/auth/ tests/unit/ -k "jwt or principal or documents" -v`

Expected: PASS (narrow as needed to existing auth/document suites)

---

### Task 4: Real-ish hook adapters behind VirusScanHook / OcrHook

**Files:**
- Create: `src/doc_pipeline/domain/hooks/adapters/__init__.py`, `src/doc_pipeline/domain/hooks/adapters/http_virus.py`, `src/doc_pipeline/domain/hooks/adapters/http_ocr.py`, `tests/unit/hooks/test_http_virus_adapter.py`, `tests/unit/hooks/test_http_ocr_adapter.py`, `tests/unit/hooks/test_hook_factory.py`
- Modify: `src/doc_pipeline/domain/hooks/stubs.py` (unchanged contract), `src/doc_pipeline/worker/processing_consumer.py` / hook factory, `src/doc_pipeline/config/settings.py` (`virus_hook_backend: Literal["stub","http"] = "stub"`, `ocr_hook_backend: Literal["stub","http"] = "stub"`, `virus_scan_url: str | None = None`, `ocr_url: str | None = None`), `.env.example`
- Test: `tests/unit/hooks/test_http_virus_adapter.py`, `tests/unit/hooks/test_http_ocr_adapter.py`, `tests/unit/hooks/test_hook_factory.py`

**Interfaces:**
- Consumes: `VirusScanHook`, `OcrHook`, `HookContext`, `VirusScanResult`, `OcrResult` (ADR-005)
- Produces:
  - `class HttpVirusScanHook: async def scan(self, ctx: HookContext) -> VirusScanResult` — POST to `virus_scan_url` with bucket/key; map JSON `{clean, scanner, scan_id}`; on `clean=false` return result (handler marks FAILED)
  - `class HttpOcrHook: async def run(self, ctx: HookContext) -> OcrResult` — POST to `ocr_url`; map `{provider, pages, text_preview, confidence}`
  - `def build_hooks(settings: Settings) -> tuple[VirusScanHook, OcrHook, ExtractHook]` — stubs default; HTTP adapters when backend=`http`
  - Extract stays stub unless explicitly extended (YAGNI — ExtractHook stub OK)
  - ClamAV sidecar: **optional** Compose service comment/docs only — do not block Task 4 if image unavailable

**Spec:** §3.4, §7.6; ADR-005

**Acceptance:**
- Default Settings still use stubs — Stage 1 tests green unchanged
- HTTP adapters honor same result types; unit tests use `httpx.MockTransport`
- Factory selects backend from Settings
- No Textract AWS SDK required; no real ClamAV Must

**Steps:**

- [ ] **Step 1: Write failing adapter + factory tests**

```python
# tests/unit/hooks/test_http_virus_adapter.py
import httpx
import pytest

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.adapters.http_virus import HttpVirusScanHook
from doc_pipeline.domain.hooks.types import HookContext
from doc_pipeline.domain.ids import generate_uuidv7


@pytest.mark.asyncio
async def test_http_virus_adapter_maps_clean_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"clean": False, "scanner": "clamav-http", "scan_id": "s-1"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hook = HttpVirusScanHook(client=client, base_url="https://av.test/scan")
        ctx = HookContext(
            tenant_id=generate_uuidv7(),
            document_id=generate_uuidv7(),
            document_type=DocumentType.INVOICE,
            bucket="b",
            key="k",
            mime_type="application/pdf",
            checksum_sha256="abc",
        )
        result = await hook.scan(ctx)
    assert result.clean is False
    assert result.scanner == "clamav-http"
    assert result.scan_id == "s-1"
```

```python
# tests/unit/hooks/test_http_ocr_adapter.py
import httpx
import pytest

from doc_pipeline.domain.enums import DocumentType
from doc_pipeline.domain.hooks.adapters.http_ocr import HttpOcrHook
from doc_pipeline.domain.hooks.types import HookContext
from doc_pipeline.domain.ids import generate_uuidv7


@pytest.mark.asyncio
async def test_http_ocr_adapter_maps_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "provider": "tesseract-http",
                "pages": 2,
                "text_preview": "Invoice #123",
                "confidence": 0.91,
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hook = HttpOcrHook(client=client, base_url="https://ocr.test/run")
        ctx = HookContext(
            tenant_id=generate_uuidv7(),
            document_id=generate_uuidv7(),
            document_type=DocumentType.INVOICE,
            bucket="b",
            key="k",
            mime_type="application/pdf",
            checksum_sha256="abc",
        )
        result = await hook.run(ctx)
    assert result.provider == "tesseract-http"
    assert result.pages == 2
    assert result.text_preview == "Invoice #123"
    assert result.confidence == pytest.approx(0.91)
```

```python
# tests/unit/hooks/test_hook_factory.py
from doc_pipeline.config.settings import Settings
from doc_pipeline.domain.hooks.stubs import StubVirusScanHook
from doc_pipeline.worker.processing_consumer import build_hooks  # or hooks/factory.py


def test_build_hooks_defaults_to_stubs() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        aws_region="eu-central-1",
        s3_bucket="b",
        sqs_queue_url="http://localhost/q",
        sqs_dlq_url="http://localhost/dlq",
        jwt_public_key_pem="-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
        virus_hook_backend="stub",
        ocr_hook_backend="stub",
    )
    virus, ocr, extract = build_hooks(settings)
    assert isinstance(virus, StubVirusScanHook)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/hooks/test_http_virus_adapter.py tests/unit/hooks/test_http_ocr_adapter.py tests/unit/hooks/test_hook_factory.py -v`

Expected: FAIL

- [ ] **Step 3: Implement adapters + factory; keep stubs default**

- [ ] **Step 4: Run hook unit suite**

Run: `uv run pytest tests/unit/hooks/ -v`

Expected: PASS (include existing stub contract tests)

---

### Task 5: Terraform autoscaling + secret-rotation runbook (+ X-Ray note)

**Files:**
- Create: `docs/runbooks/secret-rotation.md`, `tests/unit/terraform/test_ecs_autoscaling_hcl.py` (optional lightweight parse) **or** rely on `terraform validate` + checkov — prefer validate evidence over brittle string tests; if a unit check is used, assert HCL contains `ApproximateNumberOfMessagesVisible` via a small pytest reading `terraform/modules/ecs/autoscaling.tf`
- Modify / Create: `terraform/modules/ecs/autoscaling.tf`, `terraform/modules/ecs/variables.tf`, `terraform/modules/ecs/outputs.tf`, `terraform/modules/secrets/main.tf` (rotation schedule resource **documented** / optional `aws_secretsmanager_secret_rotation` skeleton with `lifecycle { ignore_changes }` or comment-only if provider needs live Lambda — **prefer runbook + IAM notes over fake rotation Lambda**), `terraform/README.md` (staging vs prod apply approval), `docs/architecture.md` or `terraform/modules/adot/README` one-liner: ADOT already exports `awsxray`
- Test / verify: `make tf-validate`; optional `uv run pytest tests/unit/terraform/test_ecs_autoscaling_hcl.py -v`

**Interfaces:**
- Consumes: existing ECS cluster/services, SQS queue ARNs/names from Task 0
- Produces:
  - `aws_appautoscaling_target` + `aws_appautoscaling_policy` for **processing-worker** (and optionally ingestion-worker) scaled on `ApproximateNumberOfMessagesVisible` (AWS/SQS)
  - Variables: `worker_min_tasks`, `worker_max_tasks` (e.g. 2–20 per spec §8.1)
  - `docs/runbooks/secret-rotation.md`: rotate DB secret in Secrets Manager; ECS redeploy/restart; no secrets in git; local `.env` rotation is copy new values + recreate containers
  - Staging/prod: document manual prod apply approval in `terraform/README.md` (ADR-007)
  - Confirm ADOT `awsxray` exporter present (already in Stage 1) — no app code change

**Spec:** §3.4, §8.1, §8.3, §8.8; ADR-006, ADR-007, ADR-010

**Acceptance:**
- `terraform validate` green
- Autoscaling metric name literally `ApproximateNumberOfMessagesVisible`
- No `terraform apply` against real AWS
- Secret rotation runbook exists and is linked from `docs/runbooks/` index / README if present
- X-Ray path documented as ADOT → X-Ray (app remains OTLP-only)

**Steps:**

- [ ] **Step 1: Write failing HCL presence test (or skip to validate-only)**

```python
# tests/unit/terraform/test_ecs_autoscaling_hcl.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUTOSCALING = ROOT / "terraform" / "modules" / "ecs" / "autoscaling.tf"


def test_autoscaling_uses_queue_depth_metric() -> None:
    text = AUTOSCALING.read_text(encoding="utf-8")
    assert "ApproximateNumberOfMessagesVisible" in text
    assert "aws_appautoscaling_policy" in text or "aws_appautoscaling_policy" in text.replace(
        "\n", " "
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/terraform/test_ecs_autoscaling_hcl.py -v`

Expected: FAIL — file missing

- [ ] **Step 3: Add autoscaling.tf + secret-rotation runbook + README apply-gate notes**

Example policy shape (metric math alarm / target tracking — Implementer picks target-tracking or step; must reference queue depth):

```hcl
# terraform/modules/ecs/autoscaling.tf
resource "aws_appautoscaling_target" "processing_worker" {
  max_capacity       = var.processing_worker_max_count
  min_capacity       = var.processing_worker_min_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.processing_worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Policy must scale on ApproximateNumberOfMessagesVisible (document metric dimension QueueName)
```

Write `docs/runbooks/secret-rotation.md` (EN): when, steps for Secrets Manager rotation + ECS task recycle, local `.env` path, RACI pointer (ADR-008/010).

- [ ] **Step 4: Validate**

Run: `uv run pytest tests/unit/terraform/test_ecs_autoscaling_hcl.py -v && make tf-validate`

Expected: PASS

---

### Task 6: Optional thin UI — documented deferral (not a Stage 2 gate)

**Files:**
- Create: `docs/plans/stage2-ui-deferral.md`
- Modify: `docs/progress.md` (one line: UI deferred Stage 2 non-gate), `AGENTS.md` §10 Stage 2 note if UI path listed
- Test: none required for deferral; if Implementer ships UI instead, stack is Vite+React+TS on port **8080**, API-only, no file proxy — that path is **out of default Task 6 scope**

**Interfaces:**
- Consumes: ADR-009, spec §13.4
- Produces:
  - `docs/plans/stage2-ui-deferral.md` stating: Stage 2 gate = workers/webhooks/auth-ADR/hooks/autoscaling/evidence; UI optional; when built later: Vite+React+TS, host port 8080, calls only `/v1/*`, never streams files, exhaustive `never` for TS unions
  - Explicit non-goals: no BFF, no HTMX admin, no file upload through UI

**Spec:** §3.4 optional UI; §13; ADR-009

**Acceptance:**
- Deferral note exists and cites §13 / ADR-009
- No requirement to run `npm`/`vite` for Stage 2 evidence
- Frozen port 8080 reserved in note

**Steps:**

- [ ] **Step 1: Write deferral note**

```markdown
# Stage 2 optional UI — deferred

Per spec §13 and ADR-009, a thin Vite+React+TypeScript demo UI is **optional** and **not a Stage 2 gate**.

## When revisited
- Port: 8080
- Talks only to FastAPI `/v1/*` (Bearer JWT)
- Screens: document list, document detail + audit, stuck jobs retry/cancel, DLQ depth (admin)
- Must NOT: proxy file bytes, host OCR, mutate state outside API

## Stage 2 gate without UI
Workers split, stuck scanner, webhooks HMAC, JWT stub + Cognito ADR, hook adapters, ECS autoscaling + secret-rotation runbook, Stage 2 evidence.
```

- [ ] **Step 2: Confirm note path**

Run: `test -f docs/plans/stage2-ui-deferral.md && echo OK`

Expected: `OK`

---

### Task 7: Stage 2 evidence file (no Done label in tracked docs)

**Files:**
- Create: local SDD harness (gitignored): Stage 2 DoD evidence file (gitignored harness)
- Modify: `docs/progress.md` (Task↔spec linkage only; **no** “Stage 2 Done”)
- Test: command evidence only

**Interfaces:**
- Consumes: Tasks 0–6 outputs
- Produces: evidence checklist with command transcripts / exit codes; human owns Done

**Spec:** §3.4, §11 DoD spirit; from-zero §2.8 / §12 Stage 2; PROMPT_COMMON §5.22

**Acceptance:**
- Evidence lists: unit suites for workers/webhooks/auth/hooks, `make tf-validate`, note on Docker/integration skipped if unavailable, UI deferred path
- Tracked docs never say “Stage 2 Done”
- No git commit

**Steps:**

- [ ] **Step 1: Run gate commands (unit-first)**

```bash
uv run pytest tests/unit/worker/ tests/unit/services/test_webhook_hmac.py tests/unit/services/test_webhook_delivery.py tests/unit/auth/ tests/unit/hooks/ -v
make tf-validate
uv run pytest tests/unit/test_openapi_docs.py -v
```

Expected: all exit 0 (or document skipped integration explicitly)

- [ ] **Step 2: Write local SDD harness (gitignored): Stage 2 DoD evidence file**

Include: date, commands, pass/fail, Docker availability, UI deferred link, Cognito=stub+ADR-013, no real AWS apply.

- [ ] **Step 3: Append `docs/progress.md` linkage only**

One short bullet mapping Stage 2 Tasks → §3.4 — **without** Done wording.

---

## Self-review

1. **Spec coverage:** Every §3.4 bullet maps to Tasks 0–7 (UI = Task 6 deferral). Staging/prod manual approval = Task 5 README. X-Ray = Task 5 ADOT note (exporter already present). OAuth2 M2M deferred in ADR-013.
2. **Placeholder scan:** No TBD/TODO; no “similar to Task N”; commit steps stripped.
3. **Type consistency:** `ProcessDocumentMessage`, `TokenVerifier`, `sign_webhook_body`, `mark_stuck_jobs`, `build_hooks`, Settings field names reused across tasks.
4. **TDD completeness:** Task 0 `test_processing_hooks_path.py` + enqueue GREEN; Task 1 stuck-scanner GREEN; Task 2 webhook skip; Task 4 OCR adapter snippet; Task 3 ADR-013 M2M deferral.
5. **Environment:** No real AWS Cognito/apply; Docker optional with `@pytest.mark.integration`.
6. **Package:** All app code under `src/doc_pipeline/`. SQS only — no Kafka. Files never through API.

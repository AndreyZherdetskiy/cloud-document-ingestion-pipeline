# Architecture (C4 summary)

Product source of truth: `spec.md` §4. This note is the English C4 overview for operators and onboarding. Local demo uses **LocalStack + Compose**; target cloud path is **AWS** via Terraform modules (ADR-007).

## C4 Level 1 — System context

Client systems (ERP, CRM, partner API) call the Document Ingestion Pipeline over HTTPS (REST). Operators use the control-plane API (Stage 2+ optional UI). Notifications and audit stay inside the platform; Stage 2+ may add virus-scan / OCR / IdP providers.

**Purpose:** accept documents, process them asynchronously and reliably, persist status + append-only audit, and change infrastructure only through IaC.

## C4 Level 2 — Containers

```
Clients ──HTTPS──► ALB ──► ECS Fargate API (FastAPI control plane)
                              │
                              ├── RDS PostgreSQL (status, audit)
                              ├── ElastiCache Redis (idempotency)
                              └── issues S3 presigned PUT (no file bytes through API)

Client PUT ──► S3 documents bucket ──ObjectCreated──► SQS ingestion (+ DLQ, redrive)
                                                         │
                                                         ▼
                                              ECS Fargate ingestion-worker
                                                         │
                                                         │ PROCESS_DOCUMENT
                                                         ▼
                                              SQS processing (+ DLQ, redrive)
                                                         │
                                                         ▼
                                              ECS Fargate processing-worker (hooks)

Periodic: stuck-scanner (asyncio) — stale jobs on processing path; not on the hot SQS poll loop.

Observability: CloudWatch (+ X-Ray via ADOT) on AWS;
               Prometheus + Grafana + Jaeger locally (not Tempo).
Secrets: SSM / Secrets Manager (AWS); gitignored `.env` locally.
```

Control plane never streams document bytes. Data plane is S3 → **ingestion** SQS → ingestion-worker → **processing** SQS → processing-worker.

## C4 Level 3 — Worker components

Three Compose / ECS processes share the `doc_pipeline` Python package but separate concerns:

| Process | Queue(s) | Role |
|---------|----------|------|
| **ingestion-worker** | `dev-document-ingestion` (+ DLQ) | S3 event intake: `HeadObject`, MIME/size checks, status `UPLOADED` → `QUEUED`, enqueue `PROCESS_DOCUMENT` on the processing queue |
| **processing-worker** | `dev-document-processing` (+ DLQ) | Hook pipeline: `VirusScanHook` → `OcrHook` → `ExtractHook` (Stage 1 stubs); terminal `PROCESSED` / `FAILED` + audit |
| **stuck-scanner** | (none — DB poll) | Asyncio periodic scan for jobs stuck past `STUCK_JOB_OLDER_THAN_SECONDS`; separate from long-poll consumers |

Shared internals per worker type:

1. **MessageParser** — SQS envelope; Redis `SET NX` idempotency.
2. **IngestionHandler** — used by ingestion-worker only.
3. **ProcessingPipeline** — used by processing-worker only.
4. **JobRepository** / **AuditLogger** — SQLAlchemy; audit append-only.

## Data flow (happy path)

1. API creates `Document` (DRAFT) + upload expectation.
2. API returns presigned PUT to `s3://{bucket}/{tenant_id}/{document_id}/{filename}`.
3. Client uploads directly to S3.
4. S3 `ObjectCreated:*` → **ingestion** SQS (`{env}-document-ingestion`).
5. **ingestion-worker** long-polls ingestion queue; visibility timeout covers P99 intake. S3 `s3:TestEvent` (bucket notification handshake) is ACK'd and deleted without processing.
6. Idempotency → HEAD object → validate → enqueue processing message → `QUEUED` + audit.
7. **processing-worker** long-polls **processing** SQS (`{env}-document-processing`); runs hooks → terminal status + audit rows.
8. **stuck-scanner** periodically finds stale processing jobs and records operator-visible state (not a third SQS consumer on the hot path).
9. After `maxReceiveCount=5` on either queue, message lands in that queue's DLQ; operators replay after fix (`docs/runbooks/dlq-replay.md`).

## LocalStack vs AWS

| Concern | Local (Compose) | AWS target |
|---------|-----------------|------------|
| Objects / queues | LocalStack: `dev-document-ingestion` + `dev-document-processing` (each + DLQ) | S3 + two SQS work queues (+ DLQs + redrive) |
| API / worker compute | Compose `api`, `ingestion-worker`, `processing-worker`, `stuck-scanner` | ECS Fargate services (split) behind ALB |
| Database / cache | Compose Postgres + Redis | RDS + ElastiCache |
| Secrets | `.env` + Pydantic Settings | SSM + Secrets Manager |
| Metrics / traces | OTel → Collector → Prometheus + **Jaeger** | ADOT → CloudWatch EMF + X-Ray |
| Dashboards / alerts | Grafana + `infra/prometheus/alerts.yml` | CloudWatch dashboard + Appendix B alarms |
| Infra changes | N/A (Compose files) | Terraform modules only; GHA OIDC plan/apply |
| Auth (Stage 1) | Local JWT keys | Cognito is Stage 2+ Must-not for Stage 1 |

Compose project / network: `doc-pipeline`. Frozen ports and demo script: root `README.md`. Ownership: `docs/ownership-raci.md` (ADR-008).

Terraform modules (not applied from this repo by default) include S3→SQS `ObjectCreated` notification on the documents bucket and a KMS key policy allowing S3 to publish to SSE-KMS SQS; wire outputs per [`terraform/environments/README.md`](../terraform/environments/README.md).

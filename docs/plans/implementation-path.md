# Implementation path — Stage 1 → 2 → 3

High-level map from `spec.md` §3.3–3.5. Detailed Task files/Acceptance appear only after CREATE_S1 (and later CREATE_S2/S3). **Stage 1 plan TBD until CREATE_S1** — do not invent Task numbers here beyond phase labels.

**Entry:** [`AGENTS.md`](../../AGENTS.md) §10. Agent roadmap: [`docs/agentic/stage-roadmap.md`](../agentic/stage-roadmap.md).

## Stage 1 — MVP

Prove: control-plane API, presign upload to S3, S3→SQS→Fargate-equivalent worker with hook stubs, PostgreSQL status+audit, LocalStack demo, Terraform modules (`validate` only), RACI, OTel→Collector→Prometheus+Jaeger.

| Phase | Build |
|-------|--------|
| P0 | Canon (AGENTS/ADRs/agentic) then tooling (uv, pytest 8, `create_app`, OpenAPI lock) |
| P1 | Compose: Postgres, Redis, LocalStack, queues/bucket, otel-collector, Prometheus, Jaeger, Grafana |
| P2 | Models + Alembic + state machine TDD |
| P3 | FastAPI documents/presign/jobs/audit/health — full OpenAPI + OTel |
| P4 | Worker: S3 event → stubs → PROCESSED/FAILED |
| P5 | Idempotency + DLQ redrive + admin replay |
| P6 | Terraform modules + validate + FinOps tags + CloudWatch JSON + ADOT module |
| P7 | Seed + CI + local Grafana/Jaeger demo + Stage 1 evidence |

**Not Must in Stage 1:** UI, Cognito, production OCR/AV, EKS, Kafka, real AWS apply.

Expected plan path after CREATE_S1: `docs/plans/2026-06-15-stage1-implementation-plan.md`.

## Stage 2 — Scale and integrations (roadmap)

Split ingestion/processing workers; native SQS long-poll; optional Celery stuck-job scanner; webhooks with HMAC; Cognito or JWT stub with ADR; real virus/OCR behind the same hook interfaces; ADOT → X-Ray; optional thin Vite+React+TS UI; autoscaling documented; secret rotation docs.

## Stage 3 — Enterprise hardening (roadmap)

Multi-tenant hardening ADR; DR docs (RPO/RTO); S3 Object Lock docs; Cost Explorer narrative; k6 peak 5000 docs/h on local/LocalStack; read replica plan. EKS remains **not** Must.

## Human-owned Done

Agents write evidence and progress rows. Humans own “Stage N Done” labels. Do not announce Stage completion in tracked docs.

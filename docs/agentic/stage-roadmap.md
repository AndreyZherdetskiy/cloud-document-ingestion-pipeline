# Stage roadmap — Cloud Document Ingestion Pipeline

Product stages: [`spec.md`](../../spec.md) §3.3–3.5, §11. Agent entry: [`AGENTS.md`](../../AGENTS.md) §10.  
**Stage 1 plan:** TBD until CREATE_S1 (expected `docs/plans/2026-06-15-stage1-implementation-plan.md`). Path map: [`implementation-path.md`](../plans/implementation-path.md).

## Stage 1 — MVP (spec §3.3)

| Phase | Focus | Prove |
|-------|-------|--------|
| P0 | Bootstrap AGENTS/ADRs + uv/Makefile/OpenAPI lock | uv sync; OpenAPI unit lock |
| P1 | Compose data plane + LocalStack + OTel + Prometheus + Jaeger + Grafana | health; collector OTLP |
| P2 | Models + Alembic + state machine TDD | unit |
| P3 | FastAPI documents/presign/jobs/audit/health + full OpenAPI + OTel | `/v1/docs` bar |
| P4 | Worker: S3 event → hook stubs → PROCESSED/FAILED | e2e happy + virus fail |
| P5 | Idempotency + DLQ redrive + admin replay | spec §10.3 |
| P6 | Terraform modules + validate + RACI + FinOps + CloudWatch + ADOT | `tf-validate` |
| P7 | Grafana/seed/CI + Stage 1 evidence | `make ci`; demo |

**Must:** control-plane API, presign upload, S3→SQS→worker with stubs, audit completeness, LocalStack demo, Terraform modules (validate only), RACI, OTel→Collector→Prometheus+Jaeger.  
**Not Must:** UI, Cognito, production OCR/AV, EKS, Kafka.

## Stage 2 — Scale and integrations (spec §3.4) — roadmap only

Split ingestion/processing workers; native SQS long-poll; optional Celery stuck scanner; webhooks HMAC; Cognito or JWT stub with ADR; real virus/OCR behind same interface; ADOT → X-Ray; optional thin UI; autoscaling documented; secret rotation docs.

## Stage 3 — Enterprise hardening (spec §3.5) — roadmap only

Multi-tenant hardening ADR; DR docs (RPO/RTO); Object Lock docs; Cost Explorer narrative; k6 5000 docs/h local/LocalStack; read replica plan.

**Out of Must:** EKS/K8s, multi-region active-active, operator portal as Must, PCI/PAN, blockchain.

## Human-owned labels

Write `.superpowers/sdd/progress.md` “implementer complete / reviewer APPROVE”. **Do not** announce “Stage N Done”. Evidence: local gitignored Stage N DoD evidence file.

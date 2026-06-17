# Stage 2 optional UI — deferred

Per [`spec.md` §13](../../spec.md) (especially §13.4) and [ADR-009](../adr/009-demo-without-ui.md), a thin Vite+React+TypeScript demo UI is **optional** and **not a Stage 2 gate**.

Stage 2 evidence and review focus on the control/data plane, workers, integrations, and operability — not on operator screens.

## Stage 2 gate without UI

The following items satisfy Stage 2 scope (`spec.md` §3.4) without shipping a frontend:

- Split ingestion / processing workers and native SQS long-poll
- Stuck-job scanner (asyncio default; optional Celery path documented)
- Outbound webhooks with HMAC verification
- JWT stub + Cognito-swap path ([ADR-013](../adr/013-cognito-swap-jwt-stub.md))
- Real-ish virus/OCR behind the same hook interface ([ADR-005](../adr/005-hook-stubs.md))
- ECS autoscaling + secret-rotation runbook
- Stage 2 evidence file (do not declare “Stage 2 Done” from this note alone)

Operators continue to use OpenAPI (`/v1/docs`), jobs/audit HTTP APIs, runbooks, and CloudWatch/Grafana until a UI is built.

## When revisited (frozen constraints)

| Constraint | Value / rule |
|------------|--------------|
| Stack | Vite + React + TypeScript (SPA) |
| Host port | **8080** (reserved; do not collide in Compose) |
| API surface | FastAPI `/v1/*` only, Bearer JWT |
| TypeScript unions | Exhaustive `switch` with `never` in default (repo standing rule) |

### Intended screens (read-heavy)

- Document list — filter by status, type, tenant slug
- Document detail — status, audit timeline, job link (no inline state mutation)
- Stuck jobs — list + Retry/Cancel via backend API
- DLQ depth overview (Platform Admin) — depth + replay trigger via API

### Must NOT

- Proxy or stream file bytes through the UI (no S3 presign download host, no file proxy)
- Host OCR, virus scan, or worker logic in the browser
- Mutate document state outside documented `/v1/*` endpoints
- Upload files through the UI (presign flow stays API/CLI)

## Explicit non-goals

- **No BFF** — no secondary backend-for-frontend; the SPA talks directly to FastAPI
- **No HTMX** / server-rendered admin as the primary operator surface
- **No file upload through UI** — creation and presign remain API-driven
- **No file proxy** — UI never becomes a bytes conduit for S3/object storage

## Demo without UI (unchanged)

Follow `spec.md` §13.3: OpenAPI or `curl`/`httpie`, correlation_id in logs, CloudWatch/Grafana panels, DLQ runbook + admin replay API, RACI + Terraform validate narrative.

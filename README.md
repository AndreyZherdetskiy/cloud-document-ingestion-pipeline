# Cloud Document Ingestion Pipeline

Event-driven document ingestion on AWS: invoices, KYC packs, and contracts. Clients create documents and upload binaries via **S3 presigned URLs**; the API is a **control plane** only and never streams file bytes. S3 ObjectCreated events feed the **ingestion** SQS queue; **ingestion-worker** and **processing-worker** (plus **stuck-scanner**) on ECS Fargate run pluggable stages (virus scan / OCR / extract) with full **PostgreSQL** status and append-only audit. Infrastructure is **100% Terraform modules** with GitHub Actions plan/apply gates and OIDC (no long-lived AWS keys in git).

## Control plane vs data plane

| Plane | Responsibility |
|-------|----------------|
| Control (FastAPI) | Create document, issue presign, query status/jobs/audit, admin replay |
| Data (S3) | Object storage; client PUT via temporary URL |
| Async (SQS → workers) | Ingestion queue → `ingestion-worker`; processing queue → `processing-worker`; `stuck-scanner` for stale jobs; DLQ after five receives |

## Presign flow (Stage 1)

Authenticate with JWT → `POST` document → `POST` upload presign → client `PUT`s the file to S3 (LocalStack locally, AWS in target environments) → S3 notifies the **ingestion** SQS queue → `ingestion-worker` validates the object and enqueues processing → `processing-worker` runs hook stubs and writes audit rows → poll document status via API. Live contract: [`http://localhost:8000/v1/docs`](http://localhost:8000/v1/docs) (once Compose is up).

## LocalStack vs AWS

| Concern | Local | AWS target |
|---------|-------|------------|
| Objects / queues | LocalStack: ingestion + processing SQS (each + DLQ); in-network URLs `http://localstack:4566/000000000000/dev-document-*` (`SQS_ENDPOINT_STRATEGY=off`, `LOCALSTACK_HOST=localstack:4566`) | S3 + two SQS work queues (+ DLQs) |
| Compute | Compose `api`, `ingestion-worker`, `processing-worker`, `stuck-scanner` | ECS Fargate (split services) |
| Secrets | gitignored `.env` + Settings | SSM + Secrets Manager |
| Metrics / traces | OTel → Collector → Prometheus + Jaeger | ADOT → CloudWatch EMF + X-Ray |
| Infra changes | N/A locally | Terraform modules only; apply on human GO |

## Frozen host ports

| Service | Host port |
|---------|-----------|
| api | 8000 |
| postgres | 5432 |
| redis | 6379 |
| localstack | 4566 |
| otel-collector OTLP | 4317, 4318 |
| prometheus | 9090 |
| grafana | 3000 |
| jaeger | 16686 |
| optional UI (Stage 2+) | 8080 |

Compose project name / network: **`doc-pipeline`** (Make always passes `-p`; no system/container prune — image prune is project-labeled). Named volumes use the same hyphen syntax (`doc-pipeline-postgres-data`).

## Quick start

Prerequisites: `uv`, Docker Compose. Bring data plane up (`make compose-up`), then observability (`make observability-up`) and app services (`make stack-up`), or use `make stack-up` alone for the full stack. Default `compose-up` is postgres+redis+localstack only.

```bash
cp .env.example .env
uv sync --group dev
make hooks          # or: uv run pre-commit install
make gen-dev-jwt    # RSA keypair → gitignored JWT files; patches .env
make migrate
make seed
make seed-prod-like
make live-demo      # create → presign → PUT → poll PROCESSED
make test-e2e       # pytest live stack (skipped when API down)
```

**Prod-like characterization (not spec §8 SLA):** `make perf-up` applies `docker-compose.perf.yml` — one API replica with four uvicorn workers, `RATE_LIMIT_PER_MINUTE=0`, small SQLAlchemy pools, OTel off, and two replicas each of `ingestion-worker` and `processing-worker`. Tear down with `make stack-down` (includes the perf overlay so scaled replicas do not linger).

Live API contract: [`http://localhost:8000/v1/docs`](http://localhost:8000/v1/docs). Swagger is at `/v1/docs`; `/docs` redirects there.

**JWT:** the API reads `JWT_PUBLIC_KEY_PEM` from Compose env interpolation (Settings unescapes `\n`). No host bind of `public.pem`. Host `make gen-dev-jwt` still writes `.local/jwt/*.pem` for minting; private key stays on the host and is never mounted into the API.

**WSL2:** if published `:8000` RST from the Linux distro while containers are healthy, use Windows `localhost`, `docker exec` into the API container, or the in-network demo below.

**In-network live demo:** one-off container on network `doc-pipeline`, mount **private key only** (never into API), `LIVE_DEMO_IN_NETWORK=1`, `BASE_URL=http://api:8000`, in-network `DATABASE_URL` (`@postgres:5432`), then `scripts/live_ingest_demo.py`. Host `make live-demo` rewrites presign PUT `localstack` → `127.0.0.1` for published LocalStack.

Static checks (no Compose): `uv sync`, `make ci`, `make export-openapi`.

Apps export **OTLP only** to the collector (`4317`/`4318`); metrics land in Grafana at `:3000`, traces in Jaeger at `:16686` (`doc-pipeline-api`, `doc-pipeline-ingestion-worker`, `doc-pipeline-processing-worker`).

## Cost estimate (staging, eu-central-1)

Rough **estimate** for a staging-like footprint: **~$200–350 / month** (S3, SQS, Fargate, RDS, ElastiCache, NAT, CloudWatch, Secrets Manager). Production with autoscaling and Multi-AZ is higher (order-of-magnitude **~$800–1500 / month** at Stage 2 assumptions). Tags: `Project=doc-pipeline`, `Environment`, `Tenant`, `CostCenter`, `Owner`. See `spec.md` §5.5.

## Docs

| Doc | Purpose |
|-----|---------|
| [`AGENTS.md`](AGENTS.md) | Agent entry, invariants, gates |
| [`docs/adr/`](docs/adr/) | Accepted architecture decisions |
| [`docs/ownership-raci.md`](docs/ownership-raci.md) | Who owns S3, SQS, IAM, DLQ |
| [`docs/plans/implementation-path.md`](docs/plans/implementation-path.md) | Stage 1→2→3 map |
| Task↔spec ledger | Local SDD harness (gitignored) |
| [`docs/slo.md`](docs/slo.md) | SLI→SLO, metric names, alert thresholds |
| [`docs/architecture.md`](docs/architecture.md) | C4 summary; LocalStack vs AWS |
| [`docs/runbooks/`](docs/runbooks/) | DLQ, backlog, stuck jobs, presign, IAM, OTel, [secret rotation](docs/runbooks/secret-rotation.md), [DR RPO/RTO](docs/runbooks/dr-rpo-rto.md), [Object Lock + Glacier](docs/runbooks/s3-object-lock-glacier.md), [Cost Explorer / FinOps](docs/runbooks/cost-explorer-finops.md) |
| [`spec.md`](spec.md) | Product SoT (English) |

## Operator happy path (~8–10 min)

Stage 1 demo does **not** require a UI (ADR-009). Suggested flow:

1. Context: manual queue pain → event-driven AWS ingestion.
2. OpenAPI at `http://localhost:8000/v1/docs`: create document → presign → show bytes never hit the API.
3. Client PUT to S3/LocalStack → ingestion SQS → `ingestion-worker` → processing SQS → `processing-worker` (logs carry `correlation_id`).
4. `GET` document status + audit chain (state machine).
5. Grafana `:3000` (throughput / DLQ / queue age) + Jaeger `:16686` (`doc-pipeline-api` → `doc-pipeline-ingestion-worker` → `doc-pipeline-processing-worker`; spans include `POST /v1/documents`, `ingest.handle_message`, `process.handle_message`); mention DLQ alert and [`docs/runbooks/dlq-replay.md`](docs/runbooks/dlq-replay.md).
6. Terraform modules + GHA plan/apply OIDC stubs; one line on [`docs/ownership-raci.md`](docs/ownership-raci.md).

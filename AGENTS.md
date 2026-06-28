# AGENTS.md — Cloud Document Ingestion Pipeline

**Entry point** for all agent and subagent development in this repository. Product source of truth: [`spec.md`](spec.md) **v3.1** (English product SoT). Do **not** duplicate the spec as `TZ.md`.

Before any Task, phase, plan, review, or code change, the agent (parent and subagent) **must** rely on this file: §1–9 — standing rules; §10 — operational links for the active stage. Details live in [`docs/`](docs/) — only invariants, navigation, and responsibilities are here; discrepancies with `docs/` are resolved by updating **this** file (see §0.3).

| Next | Path |
|------|------|
| Product / DoD / stack | [`spec.md`](spec.md) |
| Implementation path | [`docs/plans/implementation-path.md`](docs/plans/implementation-path.md) |
| Workflow | [`docs/agentic/workflow.md`](docs/agentic/workflow.md) |
| Skills | [`docs/agentic/skills-map.md`](docs/agentic/skills-map.md) |
| Stage roadmap | [`docs/agentic/stage-roadmap.md`](docs/agentic/stage-roadmap.md) |
| Subagent roles | [`docs/agentic/role-prompts/`](docs/agentic/role-prompts/) |
| Ownership RACI | [`docs/ownership-raci.md`](docs/ownership-raci.md) |
| Phase prompts (local) | §10.1 |

---

## 0. Reading order and `docs/` map

### 0.1. Required reading order

1. **`AGENTS.md`** (this file) — environment, invariants, orchestration, gates, anti-patterns, stage §10.
2. **`spec.md`** — affected product §§, DoD §11, stack §5, structure §9, tests §10, ADR summaries §12.
3. **`docs/adr/`** — Accepted ADRs (+ amendments) relevant to the task.
4. **`docs/plans/`** — active implementation plan (Files, Steps, Acceptance) when present.
5. **`docs/agentic/`** — workflow, skills, role-prompts. Phase prompts per §10.1 live in the **local SDD harness (gitignored)** — not product docs.
6. As needed: **`docs/runbooks/`**, **`docs/slo.md`**, **`docs/architecture.md`**, root README.

A subagent receives a self-contained brief; if the brief references spec/ADR/`docs/` — read those files, do not rely on parent "memory".

### 0.2. `docs/` map (what to use)

| Section | Purpose | When to read |
|---------|---------|--------------|
| [`docs/adr/`](docs/adr/) | Architecture decisions (presign, S3→SQS, UUIDv7, Fargate, Terraform OIDC, RACI, hooks) | Any task touching a pattern; Gate A |
| [`docs/plans/`](docs/plans/) | Implementation path + stage-by-stage plans | Orchestration and Implementer of active stage |
| [`docs/agentic/`](docs/agentic/) | Workflow, skills, role-prompts | Subagent dispatch |
| Local SDD phase prompts (gitignored harness) | Phase / harness prompts | Phase start; not product docs |
| [`docs/openapi/`](docs/openapi/) | Snapshot + pointer README only — live contract is `/v1/docs` | HTTP / contract tests |
| [`docs/runbooks/`](docs/runbooks/) | DLQ replay, queue backlog, stuck jobs, presign expired, IAM AccessDenied, OTel export fail, Cost Explorer / FinOps | Ops, NFR §8 |
| [`docs/slo.md`](docs/slo.md) | SLI→SLO, metric names (tenant **slug** attributes), alert thresholds; Jaeger not Tempo | Observability, DoD, NFR |
| [`docs/architecture.md`](docs/architecture.md) | C4 from spec §4; LocalStack vs AWS | Onboarding |
| [`docs/ownership-raci.md`](docs/ownership-raci.md) | Cloud ownership matrix (ADR-008) | Infra / Gate A |
| `.superpowers/sdd/progress.md` | Task↔spec linkage (gitignored local SDD harness; no Task N in app code) | After each Task |

Conflict priority: **product invariant** → `spec.md` + Accepted ADR; **Task / Acceptance order** → active plan; **agent operational rules** → `AGENTS.md`; **library/AWS APIs** → official docs for majors from spec §5 (Grounding).

### 0.3. Keeping `AGENTS.md` in sync when `docs/` changes

`AGENTS.md` must remain the current entry point. **In the same task / session** where files under `docs/` change, the agent **must** review and update the corresponding sections of this file when needed:

| Change in `docs/` | Update in `AGENTS.md` |
|-------------------|------------------------|
| New / renamed ADR, Accepted status change | §2 (invariants / ADR refs), §0.2, §10 if stage-impact |
| New or shifted plan / Tasks / checkpoints | §10 (phase tables, stops, plan paths) |
| New or updated local SDD phase prompts / index / common prompt | §10.1, phase tables; if contract changes — §5–6 |
| Edits to `workflow.md` / `skills-map.md` / `role-prompts/` | §4–7, header links; anti-patterns §9 |
| New runbooks / substantial index edits | §0.2, §3, §10 if needed |
| Edits to `slo.md` | §0.2; quality/NFR wording in §2 if diverging from spec — spec first |
| Stage 2/3 plan/prompts appear | §10.3 / §10.4 |

Do not duplicate full ADR/runbook/prompt text here — only **navigation, invariants, and operational rules**. If `docs/` changed but `AGENTS.md` was not updated — the task is **not Done**.

---

## 1. Environment

- Work **locally only**: Docker Compose, LocalStack, uv, pytest, ruff, mypy, alembic, `terraform fmt/validate`, tflint, checkov, moto, local git, file edits.
- Compose project name and default Docker network: **`doc-pipeline`** (Makefile `-p` matches; never system/container prune).
- **FORBIDDEN** without explicit human command in that chat:
  - `git commit`, `git push`, `--amend`, `--force`, hard reset, `--no-verify`;
  - `gh pr create` / remote mutations;
  - `terraform apply` / `destroy` against **real AWS**;
  - `aws` CLI mutating a real account;
  - publishing images to ECR / GHCR;
  - long-lived AWS access keys in git or GitHub Secrets.
- Commits — only when the human asks. Working tree may stay dirty.
- **NEVER** update git config; **NEVER** skip hooks unless the human explicitly asks.
- **Allowed without asking:** LocalStack in Compose, moto in pytest, `terraform fmt/validate`, tflint/checkov on modules, writing apply workflows that do **not** execute against AWS.
- Subagents: Cursor built-in models only (`composer-2.5`, `cursor-grok-4.5-high`; never BYOK; never `*-fast`); **Implementer ≠ Reviewer**.
- Secrets SoT: gitignored `.env`. Tracked template: `.env.example`. App/worker/seed read **only** Pydantic Settings (`env_file=".env"`, `extra="ignore"`). Empty `OTEL_SDK_DISABLED=` must not crash bool parse.

### 1.1 Frozen host ports

| Service | Host port |
|---------|-----------|
| api | 8000 |
| postgres | 5432 |
| redis | 6379 |
| localstack | 4566 |
| otel-collector OTLP | 4317, 4318 |
| prometheus | 9090 |
| grafana | 3000 (demo `admin`/`admin` via `.env`) |
| jaeger | 16686 |
| optional UI Stage 2 | 8080 |

Worker has no public host port. Do not shuffle these ports.

### 1.2 Compose project

Project name and default Docker network: `doc-pipeline`. Named volumes use hyphens (`doc-pipeline-postgres-data`). Secrets and credentials live in gitignored `.env`; the tracked template is `.env.example`. Compose interpolates `POSTGRES_*` and `GF_SECURITY_ADMIN_*`.

---

## 2. Invariants (Global Constraints)

From `PROMPT_IMPLEMENT_FROM_ZERO` §3 / Accepted ADRs. **This product has no dual-id, no Kafka, no HMAC inbound bus, no Stage 1 UI Must.**

1. **Control / data plane split** — API never proxies file bytes ([ADR-004](docs/adr/004-presigned-upload-not-api-proxy.md)). Presign PUT to S3.
2. **S3 → SQS → worker**, not S3 → Lambda ([ADR-001](docs/adr/001-s3-sqs-not-lambda.md)). Work queue = SQS Standard + DLQ (`maxReceiveCount=5`). **No Kafka.** Celery optional Stage 2 stuck-job scanner only.
3. **At-least-once** + Redis `SET NX` + status checks. No exactly-once ([ADR-002](docs/adr/002-at-least-once-idempotency.md)).
4. **Status + audit in PostgreSQL.** Worker status path **and** job retry/cancel HTTP path: status + audit in **one** commit ([ADR-003](docs/adr/003-state-machine-audit-postgres.md)). `audit_log` append-only; app must not UPDATE/DELETE it. DB enforces this via `REVOKE UPDATE, DELETE … FROM PUBLIC` plus a `BEFORE UPDATE OR DELETE` trigger (Alembic `20260617_0002`).
5. **Hook interfaces** (`VirusScanHook`, `OcrHook`, `ExtractHook`) with Stage 1 stubs; same I/O as future Textract/ClamAV ([ADR-005](docs/adr/005-hook-stubs.md)).
6. **Compute target AWS:** ECS Fargate, not Lambda-only, not EKS as Must ([ADR-006](docs/adr/006-ecs-fargate-not-lambda-eks.md)). Local: Compose `api`, `ingestion-worker`, `processing-worker`, `stuck-scanner`.
7. **Terraform + OIDC is the only infra change path.** ClickOps forbidden without ADR ([ADR-007](docs/adr/007-terraform-oidc-only.md)). Write modules; do not apply to real AWS without human GO.
8. **RACI** in [`docs/ownership-raci.md`](docs/ownership-raci.md) ([ADR-008](docs/adr/008-cloud-ownership-raci.md)). App never “fixes” bucket policy at runtime.
9. **Stage 1 demo does not require UI** ([ADR-009](docs/adr/009-demo-without-ui.md)). Optional Vite+React+TS Stage 2+.
10. **Secrets:** SSM for non-secret config, Secrets Manager for DB ([ADR-010](docs/adr/010-secrets-ssm-secrets-manager.md)). Local: `.env` / Settings only — never git.
11. **No RDS sharding Stages 1–3.** Read replica is Stage 2–3 ([ADR-011](docs/adr/011-rds-replica-not-sharding.md)). Writes (status, audit) **only** on primary.
12. **UUIDv7 PK everywhere; no dual-id; no composite `(tenant_id, id)` PK** ([ADR-012](docs/adr/012-uuidv7-no-dual-id.md)). Natural UNIQUE `(tenant_id, idempotency_key)` on documents. `id` in API **is** that UUID — no `public_id`, no BIGINT identity.
13. **Tenant isolation:** every query filtered by `tenant_id` from JWT. Foreign ID → **404**, not 403. Hardening decision: [ADR-014](docs/adr/014-multi-tenant-row-level.md) (row-level).
14. **Poison:** after `maxReceiveCount=5` → DLQ; worker deletes SQS message only on success (or after recording terminal FAILED — document the choice; do not block the queue).
15. **Out of scope:** operator portal as Must, production OCR/AV Stage 1, multi-region AA, PCI/PAN, blockchain, mobile SDK.
16. **Auth:** `TokenVerifier` Protocol; default `AUTH_BACKEND=stub` (RS256 dev issuer). Cognito JWKS swap via `CognitoJwtVerifier` when live AWS exists ([ADR-013](docs/adr/013-cognito-swap-jwt-stub.md)); OAuth2 client credentials (M2M) deferred to live Cognito. RBAC roles per spec §2.2.
17. **MIME allowlist + max size** from tenant `config_json` (default 50 MB). Invalid MIME at worker intake → `UPLOADED → FAILED` + audit (spec §4.6 / §4.4c). Do **not** route MIME failure through `SCANNING`. Spec §6.7 omits this edge; this lock is the Stage 1 interpretation (ADR-003 amendment).
18. **Invalid state transition** → HTTP 409 / worker error, status unchanged.
19. **Hook errors** (virus/OCR/extract raise) → `FAILED` + `failure_reason` + audit in the same transaction as the status write; then delete SQS. Transient infra (DB/SQS) still raises so the message retries.

**Also standing (OpenAPI / pagination / tests / observability):**

- **Public HTTP contract = live `/v1/docs`**, `/v1/redoc`, `/v1/openapi.json` — not markdown catalogs. Local Compose **must** keep docs enabled. Bar: `info.title` professional; `info.summary` + Markdown `info.description` (control vs data plane; files never stream through API; presign PUT; JWT; Idempotency-Key; correlation UUIDv7; RFC 7807; tenant **404**); every tag described; every operation `summary` **and** `description`; `Field(description=…)` on public schema fields; JWT/`Idempotency-Key` Header descriptions; `responses=` for codes actually raised (include **409** on invalid transitions); UUIDv7 `id` only; never cite `spec.md`/ADR/`AGENTS.md` in OpenAPI prose. Lock with `tests/unit/test_openapi_docs.py`.
- **Pagination:** cursor + `limit` (default 50, max 200). Do **not** invent `offset`.
- **Correlation:** `X-Correlation-ID` (accept `X-Correlation-Id`); UUIDv7; invalid → **422**; generate if missing; echo; bind into structlog, audit, current span. Never log full presigned URLs.
- **Observability:** OTel SDK → Collector. Local: Prometheus + Grafana + **Jaeger** (not Tempo). AWS path: ADOT → CloudWatch EMF + X-Ray. Apps export **only OTLP**. Metric attributes: `tenant_slug`, `document_type`, `status`, `hook` — never `document_id` / `correlation_id`.
- **Quality:** Python 3.12; pytest **8** (`pytest>=8,<9`); `--import-mode=importlib --strict-markers`; no pytest 9 `strict = true`; no TOML `strict_markers`. Behavioral tests only.
- **Images:** non-root USER; no `COPY .env`.
- **Do not declare Stage Done.** Write local gitignored Stage N DoD evidence; human owns Done labels.
- **Anti-copy:** no Hub dual-id/Kafka/HMAC-as-bus; no billing ledger/Stripe; no OFOM gRPC/saga; no RAG/LangGraph; no Tempo; no EKS-as-Must; no Textract-as-Stage1-Must.

### 2.7 Writing tests (pytest 8)

Pin **pytest 8** (`pytest>=8,<9` + `pytest-asyncio`). Do **not** jump to pytest 9.

Config in `[tool.pytest.ini_options]`:

```toml
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
```

| Rule | Why |
|------|-----|
| `--import-mode=importlib` in `addopts` | Same basename in unit/integration is legal; pytest does not mutate `sys.path`. Helpers in `src/` or `conftest.py` — not `tests/helpers.py` imported by other tests. |
| `--strict-markers` in `addopts` | Unknown `@pytest.mark.*` is an error. Register every custom mark in `markers =`. |
| **No** TOML key `strict_markers` | pytest 8.4 treats it as unknown config. Flag is CLI/`addopts` only. |
| **No** `strict = true` | That is pytest 9. This repo stays on 8. |
| `pythonpath = ["src"]` | Package is `doc_pipeline` under `src/`. Prefer uv install; no `sys.path` hacks. |
| `asyncio_mode = "auto"` | `async def test_*` without decorating every test. |
| Fixtures + `@pytest.mark.parametrize` | No `for x in cases: assert` loops that hide which case failed. |
| `monkeypatch` for env | Prefer over `unittest.mock.patch.dict(os.environ)`. |
| `await` in async tests | Do **not** `asyncio.run()` inside a pytest-asyncio test. |
| `AsyncMock` vs `MagicMock` | `AsyncMock` **only** for async APIs. Sync methods (`session.add`) → `MagicMock`. |

**A test must execute product code** (import the package, call a function/service, `create_app().openapi()`, moto/LocalStack, parse YAML and assert **values**).

**Forbidden (Reviewer Gate B reject):**

- `assert path.is_file()` / `assert path.exists()` as the whole test.
- Grep of markdown/CI for substrings as a substitute for behavior.
- Markdown/TOC/Cyrillic/gitignore-link linters in pytest.
- AST scans of `src/` as “tests”.
- `assert CONSTANT > 0` / `assert obj is not None` with no behavior.
- Tests that require a **real AWS account**.
- Mixing Playwright/node into `make test-unit`.

**Required / keep:**

- `tests/unit/test_openapi_docs.py` — `create_app().openapi()` **and** `GET /v1/docs` 200; fail unless OpenAPI bar holds.
- Document state machine + invalid transition → 409.
- Hook contracts: stub virus/OCR/extract; `stub_virus_clean=false` → FAILED.
- Idempotency: duplicate SQS delivery → one `PROCESSED`.
- Tenant isolation: foreign `document_id` → **404**.
- moto unit: presign shape, S3 key layout, SQS delete only after success (or documented terminal FAILED).
- Seed tests **import** seed modules and call functions — do not grep seed scripts.
- Compose: parse YAML / `docker compose config` and assert service names, ports, LocalStack, collector exporters — not “file exists”.
- Terraform: `terraform validate` / tflint / checkov as **commands**, not pytest inventory of `.tf` files.

`make ci` = lint + typecheck + **unit** (moto OK). Integration/e2e marked and deselected by default.

---

## 3. Repository structure (target spec §9)

```
src/doc_pipeline/       # single Python package: api, domain, infrastructure, worker
├── main.py
├── config/settings.py
├── api/v1/             # documents, uploads, jobs, audit, health
├── domain/             # models, schemas, services, state_machine
├── infrastructure/     # aws, db, cache
├── worker/             # consumer, handlers, hooks
└── migrations/         # Alembic (or top-level alembic/ — follow plan)
alembic/                # if migrations live outside the package
terraform/modules/…     # networking, s3, sqs, ecs, rds, iam, …
tests/{unit,integration,fixtures}/
scripts/
docs/{adr,plans,agentic,runbooks,openapi}/
deploy/{Dockerfile.api,Dockerfile.worker}
docker-compose.yml
docker-compose.test.yml
Makefile, pyproject.toml, README.md
```

Application package appears starting Stage 1 Task 0 tooling — domain models from the models/Alembic task. Until then, verify docs/harness via filesystem inventory.

---

## 4. Skills / subagents

| Moment | Skill / Task | Details |
|--------|----------------|--------|
| Plan | `superpowers:writing-plans` | [`skills-map.md`](docs/agentic/skills-map.md); save under `docs/plans/`; **strip commit steps** |
| Product forks before code | `superpowers:brainstorming` | spec already decided — do not invent portal/Kafka/dual-id |
| Execute plan task-by-task | `superpowers:subagent-driven-development` | + [`role-prompts/orchestrator.md`](docs/agentic/role-prompts/orchestrator.md); **no** finishing-branch/PR |
| Implement Task N | — | `generalPurpose` (Implementer) |
| Review | Reviewer ≠ Implementer | [`role-prompts/reviewer.md`](docs/agentic/role-prompts/reviewer.md) |
| Security | Presign, IAM, JWT stub, tenant 404 | [`role-prompts/security.md`](docs/agentic/role-prompts/security.md) |
| Grounding | stack §5 + AWS docs / MCP | [`role-prompts/grounding.md`](docs/agentic/role-prompts/grounding.md) |
| Docs / ADR / sync AGENTS | Docs role | [`role-prompts/docs.md`](docs/agentic/role-prompts/docs.md) |
| Tests / pyramid | Test role | [`role-prompts/test.md`](docs/agentic/role-prompts/test.md) |
| Bug / red test | `superpowers:systematic-debugging` | — |
| Before “done” | `superpowers:verification-before-completion` | + §0.3 if `docs/` touched |
| Worktree | `superpowers:using-git-worktrees` | on human request |

Do **not** use `finishing-a-development-branch` or `new-branch-and-pr` unless the human asks. AWS/Terraform: official docs + AWS Knowledge MCP when available — do **not** auto-deploy.

---

## 5. Orchestration

1. Start from **this file** → active stage plan under `docs/plans/` (§0.1 / §10).
2. Per task — fresh Implementer with a self-contained prompt (Files, Interfaces, Spec §§, Acceptance, Global Constraints).
3. After implementation — a **separate** Reviewer (Gates A–D). Same agent must not APPROVE itself.
4. Parallel Task only when explicitly marked in plan + sync point; **never** two implementers on the same paths.
5. Stop-the-line: REQUEST CHANGES / red tests / grounding failure / security BLOCK → fix → re-review.
6. Between ordinary tasks within a phase, do not ask "continue?".
7. Human checkpoint / BLOCKED — stop until explicit human command. Do **not** declare Stage N Done; write evidence files.
8. Changed `docs/` → update `AGENTS.md` (§0.3) before declaring the task complete.

---

## 6. Review Gates (every task)

| Gate | This product |
|------|----------------|
| **A Spec/ADR** | Presign not proxy; S3→SQS; UUIDv7 no dual-id; audit append-only; tenant 404; hooks interface; Terraform-only infra story; SQS not Kafka |
| **B Quality** | SQLAlchemy 2 async no lazy-load; layout spec §9; ruff/mypy; OpenAPI tests if HTTP (full §2 bar); `terraform validate` if TF touched; reject inventory tests; pytest 8 `addopts` |
| **C Security/ops** | Secrets not in git; Settings reads `.env` only; IAM modules no `*`; no presigned URLs in logs; OTLP to Collector/ADOT; low-card metric attributes |
| **D Failure** | Duplicate SQS → one PROCESSED; virus stub fail → FAILED+audit; 5 failures → DLQ; invalid transition 409; ready fails if PG down |

Verdict: **APPROVE** | **REQUEST CHANGES**. Working tree may be uncommitted — review files on disk, not only commit diffs.

---

## 7. Docs-grounding (libraries) and project `docs/`

- **Project `docs/`** — read per §0; do not ignore ADR/runbooks/slo in favor of "code only".
- **Official library docs** (Grounding) required for stack §5 patterns:
  - FastAPI metadata / OpenAPI / path operation config / additional responses / header params
  - Pydantic v2 + Pydantic Settings (`env_file=".env"`)
  - SQLAlchemy 2 asyncio; Alembic
  - boto3 S3 `generate_presigned_url`; S3→SQS event notifications; SQS visibility/redrive
  - IAM least privilege (no `Action: "*"` on task roles)
  - LocalStack S3/SQS; moto 5
  - OpenTelemetry Python + Collector; Prometheus OTLP; Jaeger native OTLP (**not Tempo**)
  - pytest 8.4 (`--import-mode=importlib`, `--strict-markers`)
- AWS / Terraform / IAM / S3: official AWS docs + AWS Knowledge / IaC MCP when available.
- Spec↔library docs conflict: product invariants from spec/ADR; library APIs from current docs; trade-off → ADR amendment + update §2 / §0.2 here if needed.
- Never cite `spec.md`, ADR filenames, runbooks, this file, or gitignored paths **inside OpenAPI prose**. Restate invariants in operator language.

---

## 8. Local commands

```bash
cp .env.example .env
uv sync --group dev
make hooks          # or: uv run pre-commit install
make compose-up
make stack-up       # full stack (--build --wait; 1 process per service)
make perf-up        # non-default overlay: uvicorn --workers 4, RATE_LIMIT 0, 2× ingestion + 2× processing; characterization only — not spec §8 SLA
make migrate
make seed && make seed-prod-like
make ci
make export-openapi
make tf-validate
make stack-down     # tear down including docker-compose.perf.yml (--remove-orphans; no -v)
```

Live: `http://localhost:8000/v1/docs`, Grafana `:3000`, Jaeger `:16686`, LocalStack `:4566`.

---

## 9. Anti-patterns

- Start development / subagent dispatch without this file
- One agent writes and APPROVEs itself
- Placeholder "TBD" / "add tests" / "same as Task N"
- Multipart upload through FastAPI as the main path
- Markdown API catalogs; empty `/v1/docs`; operations with `summary` but no `description`
- Auth/`Idempotency-Key` headers without `description`; stale OpenAPI snapshot vs `create_app().openapi()`
- Citing `spec.md` / ADR filenames in OpenAPI prose
- `app.mount("/metrics")`; PutMetricData / `prometheus_client` **instead of** OTel; skipping Collector
- Tempo; X-Ray SDK **in addition to** OTel (use ADOT/OTel only)
- Dual-id / Kafka / `public_id`+BIGINT / composite `(tenant_id, id)` PK / outbox-as-Must / EKS-as-Must / Textract-as-Stage1-Must
- `terraform apply` real AWS; ClickOps “just create the bucket in console”
- `Action = "*"` on IAM; presigned URLs in logs; UPDATE/DELETE `audit_log`
- 403 instead of 404 for cross-tenant
- Celery as S3 ingestion bus; root container user; `COPY .env` in image
- Inventory pytest: `is_file()`, README/Makefile/CI grep
- pytest 9 `strict = true` or TOML `strict_markers` while pinned to pytest 8
- Commits or pushes without human command; declaring Stage Done without evidence file
- Linking gitignored harness paths from tracked EN markdown
- Change `docs/` without updating corresponding `AGENTS.md` sections (§0.3)
- `composer-2.5-fast` / BYOK subagents
- Copying Hub dual-id/Kafka/HMAC-as-bus, billing ledger, OFOM saga/mesh, or RAG patterns

---

## 10. Stage development (supplement)

### 10.1. Common entry

| Artifact | Path |
|----------|------|
| Workflow | [`docs/agentic/workflow.md`](docs/agentic/workflow.md) |
| Role prompts | [`docs/agentic/role-prompts/`](docs/agentic/role-prompts/) |
| Phase prompts (local) | **local SDD harness, gitignored** — do not link those paths from this file |
| Skills map | [`docs/agentic/skills-map.md`](docs/agentic/skills-map.md) |
| Progress / DoD evidence | `.superpowers/sdd/progress.md` (gitignored local harness) |
| ADR | [`docs/adr/`](docs/adr/) |
| RACI | [`docs/ownership-raci.md`](docs/ownership-raci.md) |
| Implementation path | [`docs/plans/implementation-path.md`](docs/plans/implementation-path.md) |

Read [`docs/agentic/workflow.md`](docs/agentic/workflow.md) and the active stage plan before any phase work. Phase / common prompts live in the local SDD harness (gitignored); Orchestrator loads them from there — they are not product documentation.

### 10.2. Stage 1 — MVP (`spec.md` §3.3)

**Plan:** [`docs/plans/2026-06-15-stage1-implementation-plan.md`](docs/plans/2026-06-15-stage1-implementation-plan.md)

| Phase | Focus | Prove |
|-------|--------|-------|
| P0 | Bootstrap AGENTS/ADRs/uv/git + Task 0 tooling | uv sync; OpenAPI lock |
| P1 | Compose: PG, Redis, LocalStack, queues/bucket, otel-collector, Prometheus, Jaeger, Grafana | health; collector OTLP |
| P2 | Models + Alembic + state machine TDD | unit |
| P3 | FastAPI documents/presign/jobs/audit/health full OpenAPI + OTel | `/v1/docs` bar; Prom series |
| P4 | Worker: S3 event → hooks stubs → PROCESSED/FAILED | e2e happy + virus fail |
| P5 | Idempotency + DLQ redrive + admin replay | spec §10.3 scenarios |
| P6 | Terraform modules + validate + RACI + FinOps tags + CloudWatch JSON + ADOT collector module | `tf-validate` |
| P7 | Grafana/Prom/Jaeger local + seed + CI + evidence | `make ci`; demo; Jaeger api→worker |

**Stage 1 Must:** control-plane API, presign upload, S3→SQS→worker with stubs, audit completeness, LocalStack demo, Terraform modules (validate only), RACI, OTel→Collector→Prometheus+Jaeger. **Not Must:** UI, Cognito, Textract/ClamAV production, EKS, Kafka.

### 10.3. Stage 2 — Scale and integrations (`spec.md` §3.4)

**Plan:** [`docs/plans/2026-06-17-stage2-implementation-plan.md`](docs/plans/2026-06-17-stage2-implementation-plan.md)

Split ingestion/processing workers; native SQS long-poll; optional Celery stuck scanner (asyncio default); webhooks HMAC; JWT stub + Cognito-swap ADR-013; real-ish virus/OCR behind same interface; ADOT → X-Ray (already in TF); optional thin UI not a gate — **deferred:** [`docs/plans/stage2-ui-deferral.md`](docs/plans/stage2-ui-deferral.md) (port 8080 reserved); autoscaling documented; secret rotation docs. Task↔spec rows for Stage 2 Tasks 0–7 live in `.superpowers/sdd/progress.md`; DoD command evidence stays in the **local SDD harness** (gitignored) — **Do not declare Stage Done.** Prefer unit/moto/`tf-validate` first; live Compose probes when Docker is up.

### 10.4. Stage 3 — Enterprise hardening (`spec.md` §3.5)

**Plan:** [`docs/plans/2026-06-18-stage3-implementation-plan.md`](docs/plans/2026-06-18-stage3-implementation-plan.md)

Multi-tenant hardening ADR-014 (row-level keep); DR docs (RPO/RTO); Object Lock docs; Cost Explorer narrative; k6 5000 docs/h local/LocalStack; read replica plan — [`docs/plans/stage3-read-replica.md`](docs/plans/stage3-read-replica.md) (ADR-011). K8s/EKS is **not** Must. Evidence: local harness `stage3-dod-evidence.md` — **Do not declare Stage Done.**

### 10.5. Ad-hoc — stack versions + full audit + perf overlay

Local gitignored harness (not Stage N; no Stage Done; no commit unless asked):

- `PROMPT_STACK_VERSION_UPGRADE.md` — current stable FastAPI/boto3/Redis + **SQS/LocalStack** (not Kafka); then Phase A of full audit
- `PROMPT_FULL_PROJECT_AUDIT_AND_DOCS.md` — live seed audit + EN operator docs + independent RU handbook
- **Stage 3 perf overlay** — `docker-compose.perf.yml` + `make perf-up` (4 uvicorn workers, `RATE_LIMIT_PER_MINUTE=0`, small DB pools, OTel off, 2× ingestion + 2× processing workers); characterization only — not spec §8 SLA. Default `compose-up` stays postgres+redis+localstack; `make stack-down` always includes the perf file so scaled replicas do not linger.

Always attach `PROMPT_COMMON.md`. Subagents: `composer-2.5` or `cursor-grok-4.5-high`; Implementer ≠ Reviewer.

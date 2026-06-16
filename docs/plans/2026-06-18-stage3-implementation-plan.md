# Cloud Document Ingestion Pipeline — Stage 3 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`.
> Implementer ≠ Reviewer. **Do not git commit.** No real AWS `terraform apply`.
> Execute per [`AGENTS.md`](../../AGENTS.md) §10. Role prompts: [`docs/agentic/role-prompts/`](../agentic/role-prompts/).
> Before Task 0: Orchestrator must have `PROMPT_PHASE_10_STAGE3.md` in local SDD harness (gitignored) ready (CREATE_S3 Next).
> Steps use checkbox (`- [ ]`) syntax for tracking.
> **Docker may be unavailable** in this WSL — prefer docs / `terraform validate` / unit first; mark live Compose/LocalStack/k6 probes as optional with honest skip notes.
> Stage 3 is **docs-heavy** + optional local k6. Do **not** declare Stage Done. Evidence only: local SDD harness (gitignored): Stage 3 DoD evidence file.

**Goal:** Harden the Stage 2 pipeline for enterprise narrative: multi-tenant ADR (row-level keep), DR/RPO/RTO runbook, Object Lock + Glacier docs (recreate caveat), Cost Explorer / FinOps + per-tenant `documents_processed`, local k6 ~5000 docs/h (or honest skip), read-replica plan (ADR-011), Stage 3 evidence — no Done label.

**Architecture:** Keep one Python package `src/doc_pipeline/`. Tenant isolation stays **row-level** `tenant_id` filter + UUIDv7 single-column PK (ADR-012 / new ADR-014). DR and Object Lock are **documentation + Terraform comments/skeleton validate-only** — never apply to a real account. Cost story uses existing OTel counter `documents_processed` with low-card `tenant_slug` (never UUID labels). Peak load proof is **local/LocalStack k6**, labelled local, not contractual SLA. Read replica is planned behind `var.enable_read_replica = false` so `make tf-validate` stays green; Compose replica is optional and **not a gate**. Files never stream through the API (ADR-004).

**Tech Stack (as of plan date 2026-06-18):** Python 3.12.x; uv; FastAPI 0.115.x; Pydantic v2; SQLAlchemy 2 async; boto3; redis-py; PyJWT; uuid6; OpenTelemetry OTLP; pytest ≥8,<9; Terraform 1.9.x + AWS provider 5.x; **k6** for local load (optional). No Kafka. No EKS YAML. No OpenSearch Must. **Current product floor:** `spec.md` §5 (e.g. FastAPI 0.141.x, redis-py 8.1.x, LocalStack 4.14.x).

## Global Constraints

Copy from `PROMPT_COMMON.md` §5 / `AGENTS.md` §2 (every task implicitly includes these):

1. **Control / data plane split** — API never proxies file bytes (ADR-004). Presign PUT to S3.
2. **S3 → SQS → worker**, not S3 → Lambda (ADR-001). **No Kafka.** Work queue = SQS Standard + DLQ (`maxReceiveCount=5`). Celery optional Stage 2 stuck-job scanner only — not the ingestion bus.
3. **At-least-once** + Redis `SET NX` + status checks. No exactly-once (ADR-002).
4. **Status + audit in one PostgreSQL transaction.** `audit_log` append-only; app must not UPDATE/DELETE it (ADR-003).
5. **Hook interfaces** (`VirusScanHook`, `OcrHook`, `ExtractHook`) — stubs/adapters behind same I/O (ADR-005).
6. **Compute target AWS:** ECS Fargate (ADR-006). Local: Compose `api` + workers. **K8s/EKS not Must** — no EKS YAML “to look bigger”.
7. **Terraform + OIDC is the only infra change path** (ADR-007). Write modules / comments / optional skeleton; do not apply to real AWS.
8. **RACI** in `docs/ownership-raci.md` (ADR-008). App never “fixes” bucket policy at runtime.
9. **Stage 1 demo does not require UI** (ADR-009). Optional UI remains deferred (Stage 2 note).
10. **Secrets:** local `.env` / Settings; AWS path SSM + Secrets Manager (ADR-010) — not applied unless human GO. Do **not** generate/commit PEM keypairs for live JWT.
11. **No RDS sharding Stages 1–3.** Writes (status, audit) **only on primary** (ADR-011). Read replica is Stage 3 plan / optional TF behind default-off flag.
12. **UUIDv7 PK everywhere; no dual-id; no composite `(tenant_id, id)` PK** (ADR-012).
13. **Tenant isolation:** every query filtered by `tenant_id` from JWT. Foreign ID → **404**, not 403. Stage 3 ADR keeps **row-level** (not schema-per-tenant).
14. **Poison:** after `maxReceiveCount=5` → DLQ; worker deletes SQS message only on success **or after recording terminal FAILED**.
15. **Auth:** JWT RS256 stub remains default (ADR-013). Live Cognito / M2M deferred — no live Cognito in this environment.
16. **Pagination:** cursor + `limit` (default 50, max 200). Do not invent `offset`.
17. **Correlation:** `X-Correlation-ID` / `X-Correlation-Id`; UUIDv7; invalid → **422**; never log full presigned URLs.
18. **OpenAPI bar** (from-zero §2.1): live `/v1/docs`; summary+description; Field/Header descriptions; `responses=` for raised codes; no `spec.md`/ADR in OpenAPI prose.
19. **Observability:** Apps export **only OTLP**. Local Jaeger; AWS ADOT → CloudWatch EMF + X-Ray. Metric attrs: `tenant_slug`, `document_type`, `status`, `hook` — never `document_id` / `correlation_id`. Reuse counter name `documents_processed` — do not invent parallel UUID-labelled metrics.
20. **Quality:** Python 3.12; pytest **8**; `--import-mode=importlib --strict-markers`; behavioral tests only. Docs/ADR tasks: acceptance = `test -f` + content bullets — **no** inventory-grep pytest anti-patterns.
21. **Images:** non-root USER; no `COPY .env`.
22. **Do not declare Stage Done.** Evidence: local SDD harness (gitignored): Stage 3 DoD evidence file only. Never write “Stage 3 Done” / “Stage Done” in tracked docs.
23. **Anti-copy:** no Hub dual-id/Kafka/HMAC-as-bus; no billing ledger; no EKS-as-Must; no Textract-as-Must; no schema-per-tenant invention.
24. **No git commit / push / gh / real AWS apply** without explicit human command.
25. **Imports at module top.** No `Task N` left in application code after a task ships.
26. **Frozen ports:** api 8000, postgres 5432, redis 6379, localstack 4566, OTLP 4317/4318, prometheus 9090, grafana 3000, jaeger 16686, optional UI 8080. Workers have no public host port.
27. **Settings** from `.env` only (`env_file=".env"`, `extra="ignore"`). Empty `OTEL_SDK_DISABLED=` must not crash bool parse.
28. **S3 Object Lock:** often requires enable-at-create. Do **not** silently add `object_lock_enabled` as if it were a cheap in-place toggle on the existing bucket resource.

**Stage 3 Must NOT include:** EKS / Kubernetes YAML; OpenSearch-as-Must; live Cognito / M2M; Kafka; dual-id; billing ledger; real `terraform apply`; git commit; inventing SLA **99.9%** as proven; fake pen-test sign-off; schema-per-tenant; Object Lock apply that forces silent bucket recreate; claiming contractual SLA from local k6.

### Defer / non-goals (explicit)

| Item | Spec / ADR | Disposition |
|------|------------|-------------|
| OpenSearch | §3.5 optional | **Deferred** — Task 0 + Task 6 evidence note; not built |
| Live Cognito / OAuth2 M2M | ADR-013 | **Deferred** — stub JWT remains |
| EKS / K8s YAML | ADR-006 | **Out of scope** — Fargate only |
| Kafka / dual-id / billing ledger | Anti-copy | **Forbidden** |
| Real `terraform apply` / git commit | COMMON §3 | **Forbidden** this run |
| SLA 99.9% as proven | §3.5 | **Narrative only** in slo/DR — not claimed proven; no fake error-budget burn chart as contractual |
| Pen-test sign-off | §3.5 | **Deferred** — no fake sign-off |
| Schema-per-tenant | §3.5 ADR choice | **Rejected** in ADR-014 |

---

## File map (Stage 3)

| Path | Responsibility |
|------|----------------|
| `docs/adr/014-multi-tenant-row-level.md` | Multi-tenant hardening ADR: keep row-level; reject schema-per-tenant / dual-id / composite PK |
| `AGENTS.md` §10.4 | Point to this Stage 3 plan (was “roadmap only”) |
| `docs/runbooks/dr-rpo-rto.md` | DR narrative: RPO/RTO, S3 CRR, RDS Multi-AZ failover |
| `terraform/modules/s3/main.tf` | Comments (+ optional commented CRR / Glacier / Object Lock notes); **no** silent `object_lock_enabled` apply |
| `terraform/modules/rds/main.tf` | Comments for Multi-AZ failover; optional `aws_db_instance` replica behind `var.enable_read_replica` default `false` |
| `docs/runbooks/s3-object-lock-glacier.md` | Object Lock Compliance + lifecycle → Glacier; recreate-at-create caveat |
| `docs/runbooks/cost-explorer-finops.md` | Cost Explorer narrative + how to use `documents_processed` per `tenant_slug` |
| `docs/slo.md` | Extend Stage 3 local peak note (5000 docs/h local) + FinOps pointer; no new metric names |
| `scripts/k6/peak_5000_docs_h.js` (or `tests/load/peak_5000_docs_h.js`) | k6 constant-arrival-rate ~5000 docs/h local; JWT/`AUTH_TOKEN` + honest skip |
| `docs/plans/stage3-read-replica.md` | Read replica plan (ADR-011); Compose optional non-gate |
| local SDD harness (gitignored): Stage 3 DoD evidence file | Stage 3 evidence only (gitignored harness); no Done wording |
| `docs/progress.md` | Task↔§3.5 linkage rows only — no Done |

---

## Spec §3.5 → tasks

| §3.5 bullet | Task(s) |
|-------------|---------|
| Multi-tenant hardening (schema vs row-level — ADR) | **0** (ADR-014: row-level keep) |
| Cross-region DR: S3 replication, RDS failover | **1** |
| RDS Multi-AZ primary + read replica for list/audit; writes/audit on primary only | **1** (Multi-AZ), **5** (replica plan) |
| Audit archive: S3 Object Lock (Compliance), lifecycle → Glacier | **2** |
| Search (OpenSearch — optional) | **Deferred** (Task 0 Alternatives + Task 6 evidence) |
| Cost Explorer + `documents_processed` per tenant | **3** |
| SLA 99.9%, error budget; pen-test findings | **Deferred** as proven/sign-off (Task 3 narrative + Task 6: no fake SLA/pen-test); slo already has local SLOs |
| Load test peak 5000 docs/h | **4** (local/LocalStack or honest skip) |
| Stage 3 evidence (no Done) | **6** |

---

### Task 0: ADR-014 multi-tenant hardening (row-level keep)

**Files:**
- Create: `docs/adr/014-multi-tenant-row-level.md`
- Modify: `AGENTS.md` §2 (one ADR-014 pointer under tenant isolation / §10.4), `AGENTS.md` §10.4 (replace “roadmap only” with plan path), `docs/progress.md` (one linkage line)
- Test / verify: `test -f docs/adr/014-multi-tenant-row-level.md` + content bullets below (no inventory-grep pytest)

**Interfaces:**
- Consumes: ADR-012 (UUIDv7, no dual-id, no composite PK); ADR-011 (no sharding); existing `tenant_id` JWT filter → 404
- Produces:
  - Accepted (or Proposed→Accepted in-session) **ADR-014** deciding **row-level** multi-tenancy
  - Explicit rejection of schema-per-tenant, RLS-as-Must, dual-id, composite `(tenant_id, id)` PK
  - OpenSearch called out as **spec-optional deferred**
  - `AGENTS.md` §10.4 points at `docs/plans/2026-06-18-stage3-implementation-plan.md`

**Spec:** §3.5 multi-tenant ADR; §6.0 / ADR-012; from-zero §12 Stage 3

**Acceptance:**
- File exists with sections: Context, Decision, Consequences, Alternatives considered (template shape)
- Decision text keeps row-level `tenant_id` filter + UUIDv7 PK
- Alternatives explicitly reject schema-per-tenant and dual-id / composite PK
- OpenSearch deferred with §3.5 cite
- `AGENTS.md` §10.4 updated with plan path
- No application schema migrations in this task

**Risks:**
- Implementer invents PostgreSQL RLS as Must — reject; RLS may be noted as future optional defense-in-depth, not Stage 3 Must
- Implementer changes PK shape — Gate A fail (ADR-012)

**Steps:**

- [ ] **Step 1: Confirm ADR template + numbering**

Run: `test -f docs/adr/0000-template.md && test ! -f docs/adr/014-multi-tenant-row-level.md && ls docs/adr/01*.md`

Expected: template present; `014` absent; `013` present.

- [ ] **Step 2: Write ADR-014 (full content)**

Create `docs/adr/014-multi-tenant-row-level.md`:

```markdown
# ADR-014: Multi-tenant hardening stays row-level

- **Status:** Accepted
- **Date:** 2026-06-18
- **Spec refs:** §3.5 (schema vs row-level); §6.0; ADR-012; ADR-011

## Context

Spec §3.5 requires a multi-tenant hardening ADR choosing schema-per-tenant vs row-level isolation.
Stages 1–2 already ship a single PostgreSQL schema with `tenant_id` on domain tables, JWT-derived
tenant filters on every query (foreign ID → **404**), and UUIDv7 single-column PKs (ADR-012).
Introducing schema-per-tenant or composite PKs would force migrations, break SQS `document_id`
payloads, and conflict with Accepted ADR-012 / no-sharding ADR-011 without Stage 3 evidence of
cross-tenant leakage in the current model.

## Decision

1. **Keep row-level multi-tenancy.** Every document/job/audit query continues to filter by
   `tenant_id` from the verified JWT. Foreign tenant resources return **404**, not 403.
2. **Keep UUIDv7 single-column PK** (ADR-012). No dual-id, no BIGINT identity, no composite
   `(tenant_id, id)` primary key. Natural UNIQUE `(tenant_id, idempotency_key)` on documents remains.
3. **No schema-per-tenant** in Stages 1–3. One schema, shared migrations, shared connection pool.
4. **PostgreSQL RLS is not a Stage 3 Must.** Application-layer filters remain the gate. Future
   defense-in-depth RLS may be proposed in a separate ADR if a live threat model requires it.
5. **OpenSearch** (spec §3.5 optional search) remains **out of Stage 3 scope** — deferred until a
   product decision promotes it from optional.

## Consequences

- Continuity with existing Alembic models, OpenAPI `id` = UUIDv7, and worker message envelopes.
- Operators must keep indexing `(tenant_id, …)` for list/audit paths; replica plan (ADR-011) still applies.
- Reviewer rejects schema-per-tenant migrations, dual-id fields, and composite PK “hardening”.

## Alternatives considered

- **Schema-per-tenant** — stronger blast-radius isolation; rejected for Stages 1–3: migration/ops
  cost, connection explosion, and no demonstrated need given JWT filter + 404 semantics.
- **Composite `(tenant_id, id)` PK** — rejected by ADR-012; complicates FKs and SQS payloads.
- **Dual-id (BIGINT + public_id)** — anti-copy from Hub/billing; rejected by ADR-012.
- **RLS-as-Must now** — useful later; not required to satisfy §3.5 ADR choice and would duplicate
  app filters without changing API contracts.
- **OpenSearch now** — spec marks optional; deferred (not a Stage 3 gate).
```

- [ ] **Step 3: Update AGENTS.md §10.4 + §2 pointer**

In §10.4 replace “roadmap only” with:

```markdown
### 10.4. Stage 3 — Enterprise hardening (`spec.md` §3.5)

**Plan:** [`docs/plans/2026-06-18-stage3-implementation-plan.md`](docs/plans/2026-06-18-stage3-implementation-plan.md)

Multi-tenant hardening ADR-014 (row-level keep); DR docs (RPO/RTO); Object Lock docs; Cost Explorer narrative; k6 5000 docs/h local/LocalStack; read replica plan. K8s/EKS is **not** Must. Evidence: local harness `stage3-dod-evidence.md` — **Do not declare Stage Done.**
```

In §2 tenant isolation bullet, add: “Hardening decision: [ADR-014](docs/adr/014-multi-tenant-row-level.md) (row-level).”

- [ ] **Step 4: Verify file + required phrases**

```bash
test -f docs/adr/014-multi-tenant-row-level.md
grep -q "row-level" docs/adr/014-multi-tenant-row-level.md
grep -q "schema-per-tenant" docs/adr/014-multi-tenant-row-level.md
grep -q "ADR-012" docs/adr/014-multi-tenant-row-level.md
grep -q "OpenSearch" docs/adr/014-multi-tenant-row-level.md
grep -q "2026-06-18-stage3-implementation-plan.md" AGENTS.md
echo OK
```

Expected: all greps succeed; `OK`.

---

### Task 1: DR runbook — RPO/RTO, S3 CRR, RDS Multi-AZ failover

**Files:**
- Create: `docs/runbooks/dr-rpo-rto.md`
- Modify: `terraform/modules/s3/main.tf` (comment block for CRR — **no** live replication resources required), `terraform/modules/rds/main.tf` (comment block for Multi-AZ failover behavior; `multi_az = var.multi_az` already exists), `README.md` or `docs/architecture.md` one-line pointer to the runbook, `docs/progress.md`
- Test / verify: `test -f docs/runbooks/dr-rpo-rto.md` + content bullets; `make tf-validate` green (still **13** modules)

**Interfaces:**
- Consumes: existing `aws_s3_bucket.documents` (versioning enabled); `aws_db_instance.this` with `multi_az = var.multi_az` (default `false`); ADR-007 (validate only); ADR-011
- Produces:
  - Operator runbook with **design-target RPO/RTO numbers** (not contractual SLA)
  - S3 Cross-Region Replication (CRR) narrative + TF comment skeleton
  - RDS Multi-AZ failover narrative (automatic DNS failover; app reconnect)
  - Explicit: no real AWS apply; no multi-region active-active

**Spec:** §3.5 Cross-region DR; §8 NFR spirit; ADR-007, ADR-011

**Acceptance:**
- Runbook exists with sections: Objectives, RPO/RTO, S3 CRR, RDS Multi-AZ failover, Local vs AWS, Non-goals
- TF comments present; no new module; `make tf-validate` exit 0
- Does not claim proven 99.9% SLA

**Risks:**
- Adding real `aws_s3_bucket_replication_configuration` without destination bucket vars breaks validate — prefer **comments** or fully gated `count = 0` skeleton
- Inventing AA multi-region — reject (out of scope §2.15 AGENTS)

**Steps:**

- [ ] **Step 1: Write failing presence check (shell, not pytest inventory)**

```bash
test -f docs/runbooks/dr-rpo-rto.md
```

Expected: FAIL (exit 1) before create.

- [ ] **Step 2: Create `docs/runbooks/dr-rpo-rto.md` (full content)**

```markdown
# Disaster recovery — RPO/RTO, S3 CRR, RDS Multi-AZ

Stage 3 **documentation**. Not a contractual SLA. No real AWS failover drill is required
in this environment.

## Objectives

| Plane | Goal |
|-------|------|
| Control plane (API metadata) | Survive AZ loss via Multi-AZ RDS when enabled; reconnect clients |
| Data plane (object bytes) | Survive region loss of primary bucket via S3 CRR (when configured) |
| Audit | Same DB as status writes — primary only (ADR-011); restore from snapshots / replica promote per AWS runbooks |

## RPO / RTO (design targets)

| Scope | RPO (data loss tolerance) | RTO (time to serve again) | Mechanism |
|-------|---------------------------|---------------------------|-----------|
| Single-AZ RDS failure (Multi-AZ **on**) | ~0 for committed txns (sync standby) | Minutes (DNS failover) | RDS Multi-AZ |
| Primary region S3 loss (CRR **configured**) | Seconds–minutes (async CRR) | Hours (DNS/app endpoint cutover + IAM) | S3 CRR + versioning |
| Local Compose / LocalStack | N/A | `make compose-up` | Not DR |

These numbers are **design targets for design-review narrative**, not measured contractual SLA.
Do not claim “SLA 99.9% proven” from this document.

## S3 Cross-Region Replication (CRR)

Prerequisites (AWS): versioning on source **and** destination; IAM replication role; KMS grants if SSE-KMS.

Narrative steps (human GO + real account only):

1. Create destination bucket in secondary region (Terraform env or module).
2. Enable CRR rules for prefix (e.g. tenant uploads) or whole bucket.
3. Verify with `HeadObject` / replication metrics; document lag expectations.
4. Cutover: update app Settings / SSM `S3_BUCKET` only via Terraform + redeploy (ADR-007) — never ClickOps.

**Local:** LocalStack does not prove CRR. Skip live CRR; keep this runbook + TF comments.

## RDS Multi-AZ failover

With `multi_az = true` on `aws_db_instance`:

- AWS maintains a synchronous standby in another AZ.
- Failover updates the instance DNS endpoint; clients must reconnect (SQLAlchemy pool recycle).
- **Writes and audit stay on primary endpoint** (ADR-011). Do not point write Settings at a replica.

Failover drill (real AWS only, human GO): simulate AZ impairment per AWS docs; measure reconnect; update this runbook with actual minutes.

## Local vs AWS

| Item | Local | AWS path |
|------|-------|----------|
| Postgres | single Compose service | Multi-AZ when `var.multi_az=true` |
| S3 | LocalStack bucket | Versioned bucket + optional CRR |
| Evidence this Stage | docs + `tf-validate` | same until human apply |

## Non-goals

- Active-active multi-region API
- Automatic cross-region RDS (use replica promote / PITR playbooks when needed)
- Declaring Stage Done after writing this file
```

- [ ] **Step 3: Add TF comment skeletons (no apply)**

Append to `terraform/modules/s3/main.tf` (after lifecycle block), as comments only:

```hcl
# Stage 3 DR (docs/runbooks/dr-rpo-rto.md) — NOT applied in this validate-only run:
# - Cross-Region Replication requires a destination bucket + iam role in another region.
# - Do not add aws_s3_bucket_replication_configuration until destination module/vars exist
#   and human GO for real AWS. Versioning is already Enabled above (CRR prerequisite).
```

Append to `terraform/modules/rds/main.tf` near `multi_az`:

```hcl
  # Stage 3 DR: set multi_az=true in staging/prod tfvars for AZ failover (see docs/runbooks/dr-rpo-rto.md).
  # Failover is DNS-based; apps must reconnect. Writes/audit always use this primary endpoint (ADR-011).
  multi_az = var.multi_az
```

(Keep the existing assignment; only ensure the comment is present.)

- [ ] **Step 4: Validate**

```bash
test -f docs/runbooks/dr-rpo-rto.md
grep -q "RPO" docs/runbooks/dr-rpo-rto.md
grep -q "CRR" docs/runbooks/dr-rpo-rto.md
grep -q "Multi-AZ" docs/runbooks/dr-rpo-rto.md
make tf-validate
```

Expected: greps OK; `tf-validate` exit 0 (13 modules).

---

### Task 2: Object Lock (Compliance) + Glacier lifecycle docs

**Files:**
- Create: `docs/runbooks/s3-object-lock-glacier.md`
- Modify: `terraform/modules/s3/main.tf` (comments only for Object Lock + Glacier rule sketch), optionally `terraform/modules/s3/variables.tf` comment for future `enable_object_lock` — **default must not force recreate**, `docs/progress.md`
- Test / verify: `test -f docs/runbooks/s3-object-lock-glacier.md`; `make tf-validate`

**Interfaces:**
- Consumes: current S3 module — versioning + abort-multipart lifecycle **only**; **no** `object_lock_enabled` today
- Produces:
  - Runbook explaining Compliance mode Object Lock for audit archive objects
  - Lifecycle → Glacier (or Glacier Instant Retrieval / Deep Archive — pick one in docs and stick to it: **GLACIER**) for aged audit exports
  - **Hard caveat:** Object Lock must be enabled **at bucket create** on Amazon S3; enabling later typically means **new bucket + migrate** — never treat as a cheap toggle on `aws_s3_bucket.documents`

**Spec:** §3.5 audit archive Object Lock + Glacier; ADR-007; ADR-008 (S3 lifecycle RACI)

**Acceptance:**
- Recreate-at-create constraint documented in bold/clear section
- No `object_lock_enabled = true` added to the live `aws_s3_bucket.documents` resource in this task
- Optional commented HCL sketch only
- `make tf-validate` green

**Risks:**
- Silent `object_lock_enabled` on existing resource → plan would force replace on real apply — **forbidden** in this task
- Confusing document-upload bucket WORM with audit-export prefix — clarify prefixes in runbook

**Steps:**

- [ ] **Step 1: Confirm current module has no Object Lock**

```bash
grep -n "object_lock" terraform/modules/s3/main.tf || echo "NO_OBJECT_LOCK_OK"
```

Expected: `NO_OBJECT_LOCK_OK` (or comments only after this task).

- [ ] **Step 2: Write `docs/runbooks/s3-object-lock-glacier.md`**

```markdown
# S3 Object Lock (Compliance) + lifecycle → Glacier

Stage 3 **documentation** for audit archive (spec §3.5). Validate-only Terraform comments.
No real AWS apply in this run.

## Object Lock recreate constraint (Must read)

Amazon S3 **Object Lock** is enabled at **bucket creation** (`object_lock_enabled` on create).
You generally **cannot** turn Object Lock on for an existing bucket in place.

For this repo’s `terraform/modules/s3` bucket (`aws_s3_bucket.documents`):

- Today: versioning + abort-incomplete-multipart lifecycle only.
- Adding `object_lock_enabled = true` later is a **create-time** flag and typically forces
  **bucket replacement** (destroy/recreate) on apply — **data loss risk** unless migrated.
- **Do not** silently flip the flag in the existing resource as a “Stage 3 checkbox”.
- Correct approaches when human GO exists:
  1. **New** audit-archive bucket created with Object Lock from day one + replicate/copy, or
  2. Planned migration: new bucket → dual-write/copy → cutover Settings → retire old bucket.

## Compliance mode (narrative)

- **Compliance** retention: even root cannot shorten retention until expires (strong WORM story).
- Use for **audit export** objects (compliance packs), not necessarily every inbound upload.
- Default retention period: document product choice (e.g. 2555 days / 7 years) in tfvars when built —
  not invented as code in this Stage without human GO.

## Lifecycle → Glacier

Goal: after hot retention, transition audit-archive prefix to **GLACIER** (flexible retrieval).

Example rule intent (not applied here):

- Filter prefix: `audit-archive/`
- Transition days: e.g. 90 → `GLACIER`
- Keep abort-incomplete-multipart rule (already in module)

Current module lifecycle only aborts multipart — Glacier rule is **future** / commented.

## LocalStack

LocalStack may partially emulate Object Lock; **do not** treat local behavior as Compliance proof.
Evidence for Stage 3 = this runbook + TF comments + `tf-validate`.

## RACI

Bucket policy / lifecycle: Platform SRE Accountable per `docs/ownership-raci.md` (ADR-008).
App never mutates bucket Object Lock settings at runtime.
```

- [ ] **Step 3: Comment-only TF sketch (do not enable)**

Append to `terraform/modules/s3/main.tf`:

```hcl
# ---------------------------------------------------------------------------
# Stage 3 Object Lock / Glacier (docs/runbooks/s3-object-lock-glacier.md)
# DO NOT set object_lock_enabled on aws_s3_bucket.documents above without a
# deliberate create-new-bucket migration — enable-at-create only; in-place toggle
# risks forced replace.
#
# Future (new bucket or greenfield) sketch — commented intentionally:
# resource "aws_s3_bucket" "audit_archive" {
#   bucket              = "${var.environment}-doc-pipeline-audit-${var.account_id}"
#   object_lock_enabled = true
# }
# resource "aws_s3_bucket_object_lock_configuration" "audit_archive" { ... }
# lifecycle rule transition { days = 90; storage_class = "GLACIER" } on audit prefix
# ---------------------------------------------------------------------------
```

- [ ] **Step 4: Validate**

```bash
test -f docs/runbooks/s3-object-lock-glacier.md
grep -q "enable-at-create\|at \*\*bucket creation\*\*\|at bucket creation" docs/runbooks/s3-object-lock-glacier.md
grep -q "GLACIER" docs/runbooks/s3-object-lock-glacier.md
# Must NOT be enabled on the live documents bucket resource:
! grep -Pzo 'resource "aws_s3_bucket" "documents"[\s\S]*?object_lock_enabled\s*=\s*true' terraform/modules/s3/main.tf
make tf-validate
```

Expected: docs OK; live bucket not Object-Lock-enabled; validate green.

---

### Task 3: Cost Explorer / FinOps + per-tenant `documents_processed`

**Files:**
- Create: `docs/runbooks/cost-explorer-finops.md`
- Modify: `docs/slo.md` (Stage 3 local peak + FinOps pointer; keep canonical metric names), optionally `src/doc_pipeline/worker/handlers.py` **only if** needed to add `tenant_slug` attr to existing `_record_documents_processed` (same counter name — no new metrics), `README.md` FinOps one-liner, `docs/progress.md`
- Test / verify: `test -f docs/runbooks/cost-explorer-finops.md`; if code touched: existing unit tests still pass; **no** new inventory pytest

**Interfaces:**
- Consumes:
  - Existing OTel counter `documents_processed` in `src/doc_pipeline/worker/handlers.py` (`_record_documents_processed`)
  - Prometheus name in slo: `doc_pipeline_documents_processed_total`
  - Allowed attrs: `tenant_slug`, `document_type`, `status`, `hook` (COMMON §5.19)
  - Terraform FinOps tags: `Project`, `Environment`, `CostCenter`, `Owner`
- Produces:
  - Cost Explorer narrative (how FinOps filters by tags; how eng uses per-tenant throughput)
  - slo.md note: Stage 3 **local** peak target 5000 docs/h (not contractual)
  - If worker attrs currently omit `tenant_slug`, minimal fix: pass `tenant_slug` into the **same** counter — **do not** invent `documents_processed_by_tenant_uuid` or similar

**Spec:** §3.5 Cost Explorer + per-tenant metric; §5.5 cost; ownership-raci FinOps

**Acceptance:**
- Runbook exists; cites Cost Explorer + tag keys + `tenant_slug`
- No UUID-labelled metrics
- No duplicate counter names
- Does not claim SLA 99.9% proven

**Risks:**
- Grounding: as of Stage 2, `_record_documents_processed` may only set `status` + `document_type`. Prefer adding `tenant_slug` to attrs when the slug is already loaded on the document/tenant join — still **one** metric name.

**Steps:**

- [ ] **Step 1: Write `docs/runbooks/cost-explorer-finops.md`**

```markdown
# Cost Explorer and per-tenant throughput (FinOps)

Stage 3 narrative. No live AWS Cost Explorer API calls required in this environment.

## AWS Cost Explorer (when account exists)

1. Open Cost Explorer → group by tag `Environment` / `CostCenter` / `Owner` / `Project=doc-pipeline`
   (Terraform `default_tags` + module tags — see `terraform/README.md`).
2. Optional: link CUR to Athena for allocation; out of scope for local Stage 3.
3. Monthly review RACI: FinOps Analyst Responsible — `docs/ownership-raci.md`.

Do **not** put long-lived access keys in git to scrape Cost Explorer.

## Application metric (canonical)

| Name (OTel create_counter) | Prom / Collector view | Per-tenant attribute |
|----------------------------|-----------------------|----------------------|
| `documents_processed` | `doc_pipeline_documents_processed_total` | `tenant_slug` |

Also label with `document_type`, `status`. **Never** `document_id`, `correlation_id`, `tenant_id` UUID,
or job UUIDs on metrics (cardinality + PII-adjacent).

Local Grafana/Prom: rate by `tenant_slug` for economics conversations.

## Stage 3 load note

Spec §3.5 peak **5000 docs/h** is exercised **locally** (Task 4 k6) and labelled **local** —
not a contractual SLA and not proof of AWS 99.9%.

## Non-goals

- New metric names for “Stage 3”
- Billing ledger / Stripe-style dual-id economics (anti-copy)
- Fake pen-test or SLA certificate
```

- [ ] **Step 2: Extend `docs/slo.md`**

Add under SLI → SLO table (or after Tenant economics sentence):

```markdown
| Stage 3 local peak (design target) | k6 against local/LocalStack (`scripts/k6/peak_5000_docs_h.js`) | **~5000 docs/h** local only — see `docs/runbooks/cost-explorer-finops.md`; not contractual SLA |

FinOps: Cost Explorer tags + `documents_processed` by `tenant_slug` — `docs/runbooks/cost-explorer-finops.md`.
```

Keep existing Stage 1 “500 docs/h” row; do not delete it.

- [ ] **Step 3 (optional code): ensure `tenant_slug` on existing counter**

If review finds attrs missing `tenant_slug`, update signature only:

```python
def _record_documents_processed(
    *,
    status: str,
    document_type: str,
    tenant_slug: str,
) -> None:
    try:
        meter = metrics.get_meter("doc_pipeline.worker")
        counter = meter.create_counter("documents_processed")
        attrs = assert_low_cardinality_attrs(
            {
                "status": status,
                "document_type": document_type,
                "tenant_slug": tenant_slug,
            },
        )
        counter.add(1, attrs)
    except Exception:
        return
```

Call sites must pass the document’s tenant slug (already available via tenant relation / join — do not use UUID). Run: `uv run pytest tests/unit/worker/ -v` if this step is taken.

- [ ] **Step 4: Verify docs**

```bash
test -f docs/runbooks/cost-explorer-finops.md
grep -q "tenant_slug" docs/runbooks/cost-explorer-finops.md
grep -q "documents_processed" docs/runbooks/cost-explorer-finops.md
grep -q "5000" docs/slo.md
grep -q "Cost Explorer" docs/runbooks/cost-explorer-finops.md
```

Expected: all OK.

---

### Task 4: k6 peak ~5000 docs/h (local) or honest skip

**Files:**
- Create: `scripts/k6/peak_5000_docs_h.js` (preferred) **or** `tests/load/peak_5000_docs_h.js` if `scripts/k6/` is awkward — pick **one** path and stick to it: **`scripts/k6/peak_5000_docs_h.js`**
- Create: `scripts/k6/README.md` (run command + JWT caveat + local labelling)
- Modify: `docs/progress.md` (linkage); optionally mention in Stage 3 evidence later
- Test / verify: script file exists; `k6 run` when Docker/API up **or** documented skip in evidence — never invent PASS for create→PROCESSED

**Interfaces:**
- Consumes: `http://localhost:8000` API (live OpenAPI: `POST /v1/documents`, `POST /v1/uploads/presign`); LocalStack S3 via the returned `presigned_url`; env `AUTH_TOKEN` optional; env `BASE_URL` default `http://localhost:8000`
- Produces:
  - k6 script targeting **~5000 docs/h ≈ 1.389 docs/s ≈ 83.3/min** via `constant-arrival-rate` `rate: 84` per `1m`
  - Authenticated path: `POST /v1/documents` (`document_type: "INVOICE"`) → `POST /v1/uploads/presign` (`document_id`, `content_type`, `checksum_sha256`) → **PUT bytes to LocalStack** using `presigned_url` + `required_headers` (never through FastAPI)
  - Unauthenticated / missing token: **`GET /v1/health` only** + print/record **honest skip** of create→presign→PUT→PROCESSED

**JWT caveat (binding):**

Live Compose `.env` `JWT_PUBLIC_KEY_PEM` is a **placeholder**; pytest mints ephemeral RSA keys. Live `POST /v1/documents` currently returns **401**. Do **not** instruct implementers to generate or commit PEM keypairs (credential-handling auto-review may block). Use `AUTH_TOKEN` from the environment when a human has minted a matching token out-of-band; otherwise health-only skip.

**Spec:** §3.5 load 5000 docs/h; ADR-004 (no API file proxy); from-zero Stage 3 local/LocalStack

**Acceptance:**
- Full script shipped in repo (this plan embeds it; implementer writes the same file)
- Results labelled **local** in README + stdout banner
- Missing `AUTH_TOKEN` → skip create path honestly (not PASS)
- Never PUT file body to FastAPI

**Risks:**
- Treating health-only run as throughput proof — evidence must say **SKIPPED authenticated peak**
- Hitting real AWS S3 — forbid; LocalStack only

**Steps:**

- [ ] **Step 1: Create directory + README**

```bash
mkdir -p scripts/k6
```

Write `scripts/k6/README.md`:

```markdown
# Local peak load (k6) — Stage 3

**Label: local / LocalStack only — not contractual SLA.**

## Math

- Target: **5000 docs/h**
- 5000 / 3600 ≈ **1.389 docs/s**
- k6 `constant-arrival-rate`: `rate: 84`, `timeUnit: '1m'` ≈ 5040/h

## JWT caveat

Compose `JWT_PUBLIC_KEY_PEM` is a stub placeholder; pytest uses ephemeral keys.
Live `POST /v1/documents` often **401** without a token minted for the running API key.
Set `AUTH_TOKEN` only if you have a valid Bearer JWT for this Compose instance.
Do **not** commit PEM private keys.

## Run

```bash
# Health-only / honest skip when AUTH_TOKEN unset:
k6 run scripts/k6/peak_5000_docs_h.js

# Authenticated local peak (human-provided token):
AUTH_TOKEN="eyJ..." k6 run scripts/k6/peak_5000_docs_h.js
```

Optional: `BASE_URL=http://localhost:8000`. S3 PUT uses the API’s `presigned_url` (LocalStack when Compose is configured that way) plus `required_headers` — do not invent an unsigned bucket URL.
```

- [ ] **Step 2: Write the full k6 script**

Create `scripts/k6/peak_5000_docs_h.js` with **exactly** this content (implementer may tweak thresholds but must keep math + skip semantics):

```javascript
/**
 * Stage 3 local peak ≈ 5000 docs/h against Compose/LocalStack.
 * Results are LOCAL only — not contractual SLA.
 *
 * Math: 5000/3600 ≈ 1.389/s → constant-arrival-rate 84/min ≈ 5040/h.
 *
 * AUTH_TOKEN set  → POST /v1/documents → POST /v1/uploads/presign → PUT to
 *   LocalStack using presigned_url + required_headers (never API body).
 * AUTH_TOKEN missing → GET /v1/health only + honest skip of create→PROCESSED path.
 *
 * Contract: docs/openapi/openapi.json — DocumentType INVOICE; PresignRequest
 * requires document_id + content_type + checksum_sha256; response field is
 * presigned_url (not upload_url).
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";
const AUTHENTICATED = AUTH_TOKEN.length > 0;
const OBJECT_BODY = "k6-local-pdf-bytes";
// sha256(OBJECT_BODY) — must match x-amz-checksum-sha256 on PUT
const CHECKSUM_SHA256 =
  "4796dae0fd17c020adfdb7142cab91d162f5e24ea3729c841c0f9e8a478bb915";

const docsCreated = new Counter("local_docs_created");
const docsSkippedAuth = new Counter("local_docs_auth_skipped");

export const options = {
  scenarios: {
    peak_local_5000_per_hour: {
      executor: "constant-arrival-rate",
      rate: 84,
      timeUnit: "1m",
      duration: "2m",
      preAllocatedVUs: 10,
      maxVUs: 40,
    },
  },
  thresholds: AUTHENTICATED
    ? {
        http_req_failed: ["rate<0.05"],
        local_docs_created: ["count>0"],
      }
    : {
        // Health-only path: do not require create success.
        http_req_failed: ["rate<0.1"],
      },
  tags: {
    suite: "stage3_local_peak",
    environment: "local",
  },
};

function correlationId() {
  // UUIDv4-ish for load only; API accepts UUIDv7 — prefer env CORRELATION_PREFIX + random.
  return "00000000-0000-7000-8000-0000" + String(Math.floor(Math.random() * 1e8)).padStart(8, "0");
}

export function setup() {
  console.log("=== Stage 3 k6 LOCAL peak (not SLA) ===");
  console.log("Target ≈ 5000 docs/h (84 arrivals/min). BASE_URL=" + BASE_URL);
  if (!AUTHENTICATED) {
    console.warn(
      "AUTH_TOKEN unset: will hit /v1/health only. " +
        "Honest SKIP of create→presign→PUT→PROCESSED (live JWT often 401 with placeholder PEM).",
    );
  } else {
    console.log("AUTH_TOKEN present: authenticated create→presign→LocalStack PUT path enabled.");
  }
  return { authenticated: AUTHENTICATED };
}

export default function (data) {
  if (!data.authenticated) {
    const res = http.get(`${BASE_URL}/v1/health`, {
      tags: { name: "health_only_skip_create" },
    });
    check(res, { "health 200": (r) => r.status === 200 });
    docsSkippedAuth.add(1);
    return;
  }

  const idem = `k6-${__VU}-${__ITER}-${Date.now()}`;
  const corr = correlationId();
  const createHeaders = {
    Authorization: `Bearer ${AUTH_TOKEN}`,
    "Content-Type": "application/json",
    "Idempotency-Key": idem,
    "X-Correlation-ID": corr,
  };

  const createRes = http.post(
    `${BASE_URL}/v1/documents`,
    JSON.stringify({
      document_type: "INVOICE",
      file_name: `k6-${__VU}-${__ITER}.pdf`,
      content_type: "application/pdf",
      checksum_sha256: CHECKSUM_SHA256,
    }),
    { headers: createHeaders, tags: { name: "post_documents" } },
  );

  const created = check(createRes, {
    "create 201or200": (r) => r.status === 201 || r.status === 200,
  });
  if (!created) {
    // Do not pretend success — common when token/PEM mismatch → 401.
    return;
  }

  let body;
  try {
    body = createRes.json();
  } catch (e) {
    return;
  }
  const documentId = body.id;
  if (!documentId) return;

  const presignRes = http.post(
    `${BASE_URL}/v1/uploads/presign`,
    JSON.stringify({
      document_id: documentId,
      content_type: "application/pdf",
      checksum_sha256: CHECKSUM_SHA256,
    }),
    { headers: createHeaders, tags: { name: "post_presign" } },
  );
  if (!check(presignRes, { "presign 200": (r) => r.status === 200 })) {
    return;
  }

  let presignBody;
  try {
    presignBody = presignRes.json();
  } catch (e) {
    return;
  }
  const putUrl = presignBody.presigned_url;
  const requiredHeaders = presignBody.required_headers || {};
  if (!putUrl) return;

  // ADR-004: PUT object bytes to the presigned S3/LocalStack URL — never FastAPI.
  // Do not synthesize an unsigned LocalStack path; signature would not match.
  const putRes = http.put(putUrl, OBJECT_BODY, {
    headers: requiredHeaders,
    tags: { name: "put_localstack_s3" },
  });
  check(putRes, {
    "s3 put not api": (r) => r.url.indexOf(":8000") === -1,
    "s3 put 2xx": (r) => r.status >= 200 && r.status < 300,
  });
  docsCreated.add(1);
  sleep(0.01);
}

export function teardown(data) {
  if (!data.authenticated) {
    console.warn(
      "RESULT=LOCAL_SKIP_AUTH create→presign→PUT→PROCESSED not exercised. " +
        "Do not record PASS for peak docs/h in evidence.",
    );
  } else {
    console.log("RESULT=LOCAL_AUTH_PATH_RUN labelled local — not contractual SLA.");
  }
}
```

- [ ] **Step 3: Run k6 (or document tool missing)**

```bash
command -v k6 >/dev/null && k6 run scripts/k6/peak_5000_docs_h.js || echo "K6_MISSING_OR_SKIP"
```

Expected:

- If no `AUTH_TOKEN`: script runs health checks; teardown prints `LOCAL_SKIP_AUTH`
- If `AUTH_TOKEN` valid: creates docs; still label **local**
- If `k6` missing: evidence records skip tool — install k6 or note unavailable; do not invent PASS

- [ ] **Step 4: Confirm files**

```bash
test -f scripts/k6/peak_5000_docs_h.js
test -f scripts/k6/README.md
grep -q "84" scripts/k6/peak_5000_docs_h.js
grep -q "AUTH_TOKEN" scripts/k6/peak_5000_docs_h.js
grep -q "LOCAL_SKIP_AUTH\\|honest skip\\|Honest SKIP" scripts/k6/peak_5000_docs_h.js
grep -q "/v1/uploads/presign" scripts/k6/peak_5000_docs_h.js
grep -q "presigned_url" scripts/k6/peak_5000_docs_h.js
grep -q "INVOICE" scripts/k6/peak_5000_docs_h.js
grep -q "required_headers" scripts/k6/peak_5000_docs_h.js
grep -q "local" scripts/k6/README.md
```

Expected: all OK.

---

### Task 5: Read replica plan (ADR-011) + optional TF behind default-off flag

**Files:**
- Create: `docs/plans/stage3-read-replica.md`
- Modify: `terraform/modules/rds/variables.tf` (`enable_read_replica` default `false`), `terraform/modules/rds/main.tf` (optional `aws_db_instance` replica with `count = var.enable_read_replica ? 1 : 0`), `terraform/modules/rds/outputs.tf` (optional replica endpoint output), `docker-compose.yml` **optional comment only** — Compose replica **not a gate**, `docs/progress.md`
- Test / verify: `test -f docs/plans/stage3-read-replica.md`; `make tf-validate` (still 13 modules)

**Interfaces:**
- Consumes: ADR-011; existing primary `aws_db_instance.this`; Settings today have single `database_url`
- Produces:
  - Plan doc: list/audit **reads** may use replica; status + audit **writes** primary only
  - TF replica resource **only** when `var.enable_read_replica = true`; default **false** so validate stays green without replica prerequisites
  - Explicit: no app Settings split required in Stage 3 unless Implementer chooses a documented optional `database_read_url` — **default is docs-only + TF skeleton**; do not break Compose

**Spec:** §3.5 Multi-AZ + read replica; ADR-011

**Acceptance:**
- Plan cites ADR-011 write/audit on primary
- `enable_read_replica` defaults false
- Compose replica not required for Task 6 evidence
- `make tf-validate` exit 0
- No sharding

**Risks:**
- Pointing worker write URL at replica — Gate A fail
- Making Compose postgres replica a gate — forbidden

**Steps:**

- [ ] **Step 1: Write `docs/plans/stage3-read-replica.md`**

```markdown
# Stage 3 read replica plan (ADR-011)

## Decision reminder

- **No RDS sharding** in Stages 1–3.
- **Status + audit writes only on primary.**
- Read replica serves **list/audit/compliance read** traffic when enabled.

## Application topology (target)

| Traffic | Endpoint |
|---------|----------|
| API writes (status transitions via worker; control-plane creates) | Primary `DATABASE_URL` |
| Worker status + audit commits | Primary only |
| Optional API list/audit GET | Future `DATABASE_READ_URL` → replica (not required to ship Stage 3) |

Eventual consistency: replica lag monitoring is an ops follow-up (CloudWatch `ReplicaLag`).

## Terraform

`terraform/modules/rds`: `var.enable_read_replica` default **false**.
When true, `aws_db_instance` replica with `replicate_source_db = aws_db_instance.this.identifier`.

Do not `terraform apply` without human GO.

## Compose

Optional second Postgres service is **not a Stage 3 gate**. Local demo continues with one Postgres.
If added later for exploration, never send worker writes to it.

## Non-goals

- Aurora global database
- Sharding by `tenant_id`
- Dual-id or schema-per-tenant as “replica alternative”
```

- [ ] **Step 2: Add variable + optional replica resource**

`terraform/modules/rds/variables.tf`:

```hcl
variable "enable_read_replica" {
  description = "When true, create a same-region read replica (ADR-011). Default false for validate-only green."
  type        = bool
  default     = false
}

variable "replica_instance_class" {
  description = "Instance class for optional read replica."
  type        = string
  default     = "db.t4g.medium"
}
```

Append to `terraform/modules/rds/main.tf`:

```hcl
# ADR-011 / Stage 3: optional read replica for list/audit reads. Writes stay on primary above.
resource "aws_db_instance" "replica" {
  count = var.enable_read_replica ? 1 : 0

  identifier          = "${local.name_prefix}-db-replica"
  replicate_source_db = aws_db_instance.this.identifier
  instance_class      = var.replica_instance_class
  publicly_accessible = false
  skip_final_snapshot = true

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-db-replica", Role = "read-replica" })
}
```

`terraform/modules/rds/outputs.tf` (add):

```hcl
output "replica_address" {
  description = "Read replica address when enable_read_replica=true; else null."
  value       = try(aws_db_instance.replica[0].address, null)
}
```

- [ ] **Step 3: Compose note (comment only, non-gate)**

At top of postgres service in `docker-compose.yml` or nearby comment:

```yaml
# Stage 3: optional read replica NOT required. See docs/plans/stage3-read-replica.md (ADR-011).
```

Do not add a second DB service unless human asks.

- [ ] **Step 4: Validate**

```bash
test -f docs/plans/stage3-read-replica.md
grep -q "ADR-011" docs/plans/stage3-read-replica.md
grep -q "enable_read_replica" terraform/modules/rds/variables.tf
grep -q 'default     = false' terraform/modules/rds/variables.tf
make tf-validate
```

Expected: OK; validate green; module count still 13.

---

### Task 6: Stage 3 evidence file (no Done label)

**Files:**
- Create: local SDD harness (gitignored): Stage 3 DoD evidence file (gitignored harness)
- Modify: `docs/progress.md` (Task↔§3.5 linkage only — **no** “Stage 3 Done” / “Stage Done”)
- Test: command evidence only

**Interfaces:**
- Consumes: Tasks 0–5 outputs
- Produces: evidence checklist with commands, exit codes, honest JWT/live notes; human owns Done

**Spec:** §3.5; §11 DoD spirit; from-zero §2.8 / §12 Stage 3; PROMPT_COMMON §5.22

**Acceptance:**
- Evidence lists: ADR-014 path, DR/Object Lock/Cost/Replica docs, k6 local or honest skip, `make tf-validate`, `make ci` (or unit slice)
- Honest live note: if `POST /v1/documents` still **401** with placeholder PEM, record it — do not invent PASS
- OpenSearch deferred cited
- Tracked docs never say “Stage 3 Done” or “Stage Done”
- No git commit

**Steps:**

- [ ] **Step 1: Run gate commands (docs + validate + ci)**

```bash
test -f docs/adr/014-multi-tenant-row-level.md
test -f docs/runbooks/dr-rpo-rto.md
test -f docs/runbooks/s3-object-lock-glacier.md
test -f docs/runbooks/cost-explorer-finops.md
test -f docs/plans/stage3-read-replica.md
test -f scripts/k6/peak_5000_docs_h.js
make tf-validate
make ci
# Optional live probes (honest):
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/health || echo "API_DOWN"
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/v1/documents \
  -H "Content-Type: application/json" -d '{}' || echo "API_DOWN"
# Expect health 200 when Compose up; create often 401 without AUTH_TOKEN — record truth.
command -v k6 >/dev/null && k6 run scripts/k6/peak_5000_docs_h.js || echo "K6_SKIPPED"
```

Expected: docs present; `tf-validate` 0; `make ci` 0; live create 401 recorded if still true; k6 skip or LOCAL_SKIP_AUTH without inventing peak PASS.

- [ ] **Step 2: Write local SDD harness (gitignored): Stage 3 DoD evidence file**

Include at minimum:

```markdown
# Stage 3 DoD evidence (local harness)

Date: YYYY-MM-DD
Environment: local / no real AWS apply / no git commit

## Docs / ADR
- [ ] ADR-014 row-level — path + Decision grepped
- [ ] dr-rpo-rto.md
- [ ] s3-object-lock-glacier.md (recreate caveat)
- [ ] cost-explorer-finops.md + slo.md 5000 local note
- [ ] stage3-read-replica.md (ADR-011)
- [ ] OpenSearch deferred (spec §3.5 optional)

## Commands
- make tf-validate: exit ?
- make ci: exit ?
- k6: LOCAL_SKIP_AUTH | LOCAL_AUTH_PATH_RUN | K6_SKIPPED
- Live POST /v1/documents: status ? (401 expected without matching JWT)

## Explicit non-claims
- Not claiming Stage Done
- Not claiming SLA 99.9% proven
- Not claiming pen-test sign-off
- Not claiming Object Lock applied on live bucket
```

- [ ] **Step 3: Append `docs/progress.md` linkage only**

One short table/bullets mapping Stage 3 Tasks 0–6 → §3.5 — **without** Done wording.

---

## Self-review

1. **Spec coverage:** Every §3.5 bullet maps to Tasks 0–6 or an **explicit deferral** (OpenSearch; SLA 99.9% as proven; pen-test sign-off). Multi-tenant ADR → Task 0. DR/S3/RDS failover → Task 1. Object Lock/Glacier → Task 2. Cost Explorer + per-tenant metric → Task 3. 5000 docs/h → Task 4. Read replica → Task 5. Evidence → Task 6.
2. **Placeholder scan:** No TBD/TODO; no “similar to Task N”; commit steps stripped; full ADR/runbook/k6/TF snippets embedded.
3. **Type consistency:** Package `src/doc_pipeline/`; metric name stays `documents_processed`; TF var `enable_read_replica`; ADR-014; evidence path `stage3-dod-evidence.md`.
4. **Environment:** No real AWS apply; no EKS YAML; Object Lock not silently enabled on existing bucket; k6 labelled local; JWT 401 honest skip.
5. **Package / invariants:** UUIDv7 no dual-id; row-level tenant filter; SQS not Kafka; files never through API; writes/audit on primary only.
6. **Module count:** Prefer comments/variables on existing `s3` and `rds` — still **13** modules unless human requires a 14th (not in this plan).

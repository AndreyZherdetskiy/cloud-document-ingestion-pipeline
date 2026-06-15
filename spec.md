# Product Specification

## Cloud Document Ingestion & Processing Pipeline

**Subtitle:** Event-driven document pipeline on AWS — presigned uploads, work queues, idempotent background workers, full audit trail, and infrastructure as code  
**Product name:** Cloud Document Ingestion & Processing Pipeline (the **Pipeline**)  
**Document version:** 3.1  
**Date:** 2026-06-28  
**Status:** Ready for implementation / operations  
**Classification:** Commercial product / internal document-processing platform service  
**Target folder:** `3_aws_document_ingestion_pipeline/`  
**Audience:** Middle+/Senior backend engineers, DevOps/SRE, solutions architects, product owners, compliance, FinOps  
**Primary cloud region:** `eu-central-1` (Frankfurt); `eu-west-1` reserved for Stage 3 DR  
**Implementation language:** Python 3.12+  
**Dependency manager:** `uv` (preferred) or Poetry  

---

## 0. Glossary

Glossary precedes the main body. After first use in a section, English terms or accepted abbreviations (DLQ, IAM, IaC, OCR, API, CI/CD, RBAC, JWT, SLA, SLO, NFR, SDK, ORM) may be used alone.

### Product and domain terms

| Term | Definition / role |
|------|-------------------|
| Pipeline | End-to-end chain from file upload to terminal status `PROCESSED` / `FAILED` |
| Ingestion | Accept file + metadata: object storage write, event, enqueue |
| Processing | Async stages: virus scan, OCR, field extraction |
| Control plane | HTTP API (FastAPI): metadata, presigned URLs, statuses, audit, job retry |
| Data plane | Object storage + queues + workers: binaries and heavy processing |
| Presigned URL | Time-limited signed object-storage URL for direct upload/download without proxying bytes through the API |
| Object storage | Binary document store with prefixes by tenant and `document_id` |
| Message queue | Managed work queue between object-created events and background workers |
| Dead letter queue (DLQ) | Queue after receive exhaustion (`maxReceiveCount`); isolates poison messages |
| Redrive policy | SQS rule: when receive count exceeds threshold, message moves to DLQ |
| Retry / redelivery | Reprocessing via visibility timeout, manual API retry, or DLQ replay |
| Replay | Admin operation: move a DLQ message back to the main queue after root-cause fix |
| At-least-once delivery | Queue delivery guarantee: duplicates possible; idempotency is mandatory |
| Idempotency | Repeat request/message must not create duplicate side effects |
| Idempotency key | Client or system dedup key (API header / Redis `SET NX` / DB UNIQUE) |
| State machine | Allowed document status transitions; invalid transition → error without corrupting state |
| Audit trail / audit log | Append-only status-change history with actor, time, and `correlation_id` |
| Correlation ID | Cross-cutting request/document ID for logs, audit, and investigations |
| Trace ID | Distributed tracing ID (OpenTelemetry / X-Ray) |
| Tenant | Isolated customer in multi-tenant model; `tenant_id` filter on all rows |
| Multi-tenancy | Data and authorization separation among organizations in one deployment |
| RBAC | Roles: API client, Operator, Compliance, Admin, Platform Admin, System |
| Least privilege | IAM roles with minimum rights on scoped resource ARNs |
| Infrastructure as Code (IaC) | AWS resources described in Terraform; ClickOps forbidden without ADR |
| Terraform plan/apply gate | CI: `plan` on PR; staging `apply` automated; production requires manual approval |
| State lock | DynamoDB lock on remote Terraform state so two applies do not conflict |
| OpenID Connect (OIDC) | GitHub Actions → AWS federation without long-lived access keys |
| Hook / pluggable stage | Pipeline stage interface: virus-scan, OCR, extract (stubs → production) |
| Stub / placeholder | Hook implementation without real OCR/AV; output contract fixed |
| OCR | Text extraction from scans/PDF; Stage 1 stub; Stage 2+ Textract or vendor |
| Extraction | Transform text/document into structured JSON fields (invoice number, amounts, …) |
| Virus scan | Malware check; Stage 1 hook + stub |
| Backpressure | Queue smooths upload peaks relative to worker throughput |
| Horizontal scaling / autoscaling | Scale ECS tasks by queue depth |
| Structured logging | JSON logs with required fields (`correlation_id`, `tenant_id`, …) |
| Observability | Logs + metrics + alerts (+ tracing) |
| Liveness probe | `/v1/health` — process alive |
| Readiness probe | `/v1/ready` — PostgreSQL + Redis reachable |
| RTO | Maximum acceptable recovery time after outage |
| RPO | Maximum acceptable data loss window |
| Disaster recovery (DR) | Object-store replication, DB snapshots, failover runbook (Stage 3) |
| Chargeback / FinOps tags | AWS tags for cost allocation by project, environment, tenant |
| Poison message | Message that repeatedly fails processing; must go to DLQ, not block the queue |
| Control / data plane separation | API does not stream large files; binaries and heavy work stay off the control plane |
| Runbook | Step-by-step SRE procedure: DLQ, queue backlog, rollback |
| RACI | Responsible / Accountable / Consulted / Informed — cloud resource ownership |
| ADR | Short architecture decision record: context → decision → consequences |
| Definition of Done (DoD) | Acceptance checklist for a feature / stage |
| NFR | Performance, security, availability, observability requirements |
| SLA / SLO | External and internal measurable quality targets |
| MTTR | Mean time from failure detection to restored processing |
| UUIDv7 | Timestamp-prefixed UUID; default surrogate PK (B-tree insert locality) |
| dual-id / `public_id` | Pattern BIGINT PK + external UUID; **rejected in this product** |
| Composite primary key | Multi-column PK; only for pure M:N links without their own lifecycle |
| Natural key / UNIQUE | Business uniqueness (`tenant_id` + …) via UNIQUE constraint, not PK shape |

### AWS services (role → name)

| Role | AWS service | Purpose in the Pipeline |
|------|-------------|-------------------------|
| Document object storage | Amazon S3 | Binaries; presigned URLs; `ObjectCreated` events |
| Standard work queue | Amazon SQS (Standard) | Buffer between S3 and workers; retries via visibility timeout |
| Dead letter queue | Amazon SQS DLQ | Isolate failed messages after `maxReceiveCount=5` |
| Managed containers | Amazon ECS on AWS Fargate | Run API and workers |
| HTTPS load balancer | Application Load Balancer (ALB) | Control-plane ingress |
| Container registry | Amazon ECR | Images for `api`, `ingestion-worker`, `processing-worker` |
| Managed RDBMS | Amazon RDS for PostgreSQL | Source of truth: documents, jobs, audit; Multi-AZ + read replica (see §4.5, ADR-011) |
| Managed cache | Amazon ElastiCache for Redis | Idempotency, rate limits, short-lived locks |
| Private network | Amazon VPC | 3 AZs; private subnets for ECS/RDS/Redis |
| Egress gateway | NAT Gateway | Worker outbound traffic to external hooks |
| DNS | Amazon Route 53 | API hostname |
| TLS certificates | AWS Certificate Manager (ACM) | Certificate on ALB |
| Access control | AWS IAM | Task roles, OIDC deploy role, least privilege |
| Configuration | AWS Systems Manager Parameter Store | Non-secret config `/doc-pipeline/{env}/*` |
| Secrets | AWS Secrets Manager | DB credentials, rotation (Stage 2) |
| Encryption keys | AWS KMS (CMK) | Server-side encryption for S3/RDS/SQS |
| Logs, metrics, alarms | Amazon CloudWatch | Native AWS observability |
| Distributed tracing | AWS X-Ray (via ADOT) | End-to-end traces on the AWS path |
| Identity | Amazon Cognito (Stage 2) | OAuth2 / JWT issuer |
| Document OCR | Amazon Textract (Stage 2) | OCR provider behind hook interface |
| Event fan-out (optional) | Amazon SNS (Stage 2) | S3 → multiple subscribers |
| Visibility timeout | SQS visibility timeout | Time message is invisible to other consumers; ≥ P99 processing time |
| Receive count / maxReceiveCount | Delivery counter; on exceed → redrive to DLQ |
| SSE-KMS | Server-side encryption with customer-managed key |
| S3 Event Notification | `s3:ObjectCreated:*` → enqueue to ingestion SQS |

---

## Contents

1. [Product passport and business pain](#1-product-passport-and-business-pain)
2. [Personas, roles, and journeys](#2-personas-roles-and-journeys)
3. [Scope: in / out / Stages 1–3](#3-scope-in--out--stages-13)
4. [Architecture](#4-architecture)
5. [Technology stack](#5-technology-stack)
6. [Domain model and data schema](#6-domain-model-and-data-schema)
7. [APIs and events](#7-apis-and-events)
8. [Non-functional requirements](#8-non-functional-requirements)
9. [Repository structure](#9-repository-structure)
10. [Testing strategy and CI/CD](#10-testing-strategy-and-cicd)
11. [Acceptance criteria](#11-acceptance-criteria)
12. [Architecture decisions and FAQ](#12-architecture-decisions-and-faq)
13. [Thin demo UI (product decision)](#13-thin-demo-ui-product-decision)
14. [Product positioning and non-goals](#14-product-positioning-and-non-goals)
15. [Appendices](#appendices)

---

## 1. Product passport and business pain

### 1.1. Product passport

| Field | Value |
|-------|-------|
| **Name** | Cloud Document Ingestion & Processing Pipeline |
| **Short name** | Pipeline |
| **Type** | B2B SaaS / internal platform service |
| **Purpose** | Ingest, validate, route, and asynchronously process documents: **invoices**, KYC packs, **contracts** |
| **Product owners** | Operations + Compliance + FinOps |
| **Team** | Backend (Python), DevOps/SRE, QA, product owner; explicit RACI for cloud resources |
| **Consumers** | ERP, CRM, AML/KYC platforms; back-office operators; integrators via HTTP REST API |
| **Delivery model** | Managed AWS service; Terraform deploy; GitHub Actions CI/CD |
| **Target SLA (Stage 3)** | Control-plane API availability 99.9%; RPO ≤ 15 min; RTO ≤ 60 min |

### 1.2. Business pain (As-Is)

The organization receives **3,000–12,000 documents per day** from mixed channels:

- shared mailbox email attachments;
- legacy web portal without a programmatic API;
- overnight SFTP batches;
- partner integrations with inconsistent formats.

| # | Pain | Quantitative effect | Business risk |
|---|------|---------------------|---------------|
| P1 | Manual status queue in spreadsheets | ~8 FTE triage; ~45 min median “document → in progress” | Loss, duplicates, errors |
| P2 | No unified status audit trail | 0% traceability; investigations 4–8 h | KYC/AML fines, disputes |
| P3 | No throughput control | Peak ~800 docs/h vs sustained ~120 | SLA breach, growing backlog |
| P4 | Ad-hoc OCR / extract / virus-scan | 30–40% documents need manual entry | Data errors, period-close delay |
| P5 | No cloud cost visibility | FinOps cannot allocate spend | Uncontrolled AWS bill growth |
| P6 | No infrastructure owner (ClickOps) | “Who changed the bucket policy?” unknown | Config drift, audit failure |

### 1.3. Target state (To-Be)

1. Programmatic intake via S3 presigned URLs + HTTP metadata API.
2. Event-driven processing: S3 notification → SQS work queues → ECS/Fargate workers.
3. Full audit trail for every status transition (actor, time, `correlation_id`).
4. Horizontal worker scaling by SQS queue depth.
5. Observability: structured JSON logs, metrics, and alarms; tracing via OpenTelemetry (local Jaeger; AWS ADOT → CloudWatch/X-Ray).
6. Infrastructure as code: Terraform modules + GitHub Actions `plan`/`apply` gates.
7. Explicit RACI matrix for cloud ownership.

### 1.4. Success metrics (KPI)

| Metric | As-Is | Stage 1 target | Stage 3 target |
|--------|-------|----------------|----------------|
| Sustained throughput | ~120 docs/h | ≥ 500 docs/h | ≥ 2,000 docs/h |
| Peak throughput | ~200 docs/h (with degradation) | ≥ 1,000 docs/h | ≥ 5,000 docs/h |
| Processing latency P50 (upload → `PROCESSED`) | 2–6 h | ≤ 15 min | ≤ 5 min |
| Latency P95 | 24+ h | ≤ 60 min | ≤ 20 min |
| Audit completeness | ~0% | 100% | 100% + immutable archive |
| Manual triage share | ~70% | ≤ 30% | ≤ 10% |
| Failed-job auto-retry success | n/a | ≥ 85% | ≥ 95% |
| Mean time to detect stuck job | hours/days | ≤ 15 min | ≤ 5 min |
| Infra changes via Terraform | ~0% | 100% | 100% + DR modules |

### 1.5. Document types and required stages (Stage 1)

| Type | Code | Examples | Required stages |
|------|------|----------|-----------------|
| Invoice | `INVOICE` | PDF, PNG scan | upload → virus-scan → OCR stub → extract stub → (review queue if needed) |
| KYC | `KYC` | passport, address, selfie | upload → virus-scan → metadata validation → compliance queue |
| Contract | `CONTRACT` | PDF/DOCX | upload → virus-scan → OCR stub → legal review queue |

### 1.6. Pipeline responsibility boundaries

| Pipeline owns | Pipeline does **not** own |
|---------------|---------------------------|
| Metadata intake and presigned URL issuance | Legal review of contracts |
| Reliable async processing and statuses | Production OCR/ML accuracy (Stage 1 stubs) |
| Transition audit and tenant isolation | Full operator portal UI (see §13) |
| IaC, IAM, DLQ, observability, FinOps tags | Active-active multi-region (Stage 3) |
| Hooks with swappable implementations | Payment-card / PCI storage (out of domain) |

---

## 2. Personas, roles, and journeys

### 2.1. Personas

| ID | Persona | Description | Goals | As-Is pain |
|----|---------|-------------|-------|------------|
| PER-01 | Integration developer | Partner/internal system | Stable API, idempotency, webhooks | No API, unstable SLA |
| PER-02 | Back-office operator | Manual review | Find document, status, escalate | Spreadsheet queue, no history |
| PER-03 | Compliance officer | KYC/AML | Audit, export, immutable log | No evidentiary base |
| PER-04 | Platform SRE | Operations | Alerts, autoscaling, DLQ | Snowflake servers, manual deploys |
| PER-05 | Product owner | Backlog | Throughput / latency metrics | No dashboards |
| PER-06 | FinOps analyst | Cloud cost | Tags, per-tenant reports | No tagging |
| PER-07 | Tech Lead (platform) | Cloud ownership | RACI, plan gates, no ClickOps | Unclear S3/IAM ownership |

### 2.2. Roles and permissions (RBAC)

| Role | Code | Description | Permissions |
|------|------|-------------|-------------|
| API client | `ROLE_API_CLIENT` | Machine-to-machine | `documents:create`, `documents:read`, `uploads:presign`, `jobs:read` (own tenant) |
| Operator | `ROLE_OPERATOR` | Back-office | `documents:read`, `documents:assign`, `jobs:retry`, `jobs:cancel`, `audit:read` |
| Compliance | `ROLE_COMPLIANCE` | Audit and reports | `documents:read`, `audit:read`, `audit:export`, `jobs:read` (read-only, all tenants) |
| Tenant admin | `ROLE_ADMIN` | Tenant admin | all rights within tenant + `config:read` |
| Platform Admin | `ROLE_PLATFORM_ADMIN` | SRE / platform | cross-tenant read, DLQ replay, infra read-only |
| System | `ROLE_SYSTEM` | Worker identity | `jobs:update`, `audit:write`, SQS consume, S3 read |

**Stage 1 authentication:** JWT (RS256) from an internal identity provider; Cognito is Stage 2.  
**Authorization:** FastAPI dependencies + PostgreSQL row isolation by `tenant_id`.

### 2.3. User journeys

#### J-01: Invoice upload via API (integration developer)

```
[Client system] → POST /v1/documents (metadata)
                → POST /v1/uploads/presign
                → PUT to S3 via temporary URL
                → S3 event → ingestion SQS
                → ingestion-worker → processing SQS → processing-worker
                → GET /v1/documents/{id} (status poll)
                → (Stage 2) webhook document.processed
```

1. Client creates a logical document → `document_id`, then `upload_id`.
2. Client obtains a temporary URL and uploads directly to S3 (bypassing API body limits).
3. `ObjectCreated` lands on `document-ingestion` queue.
4. `ingestion-worker` validates MIME/size/hash, transitions `UPLOADED` → `QUEUED`, enqueues processing.
5. `processing-worker`: virus-scan stub → OCR stub → extract stub.
6. Client sees terminal `PROCESSED` or `FAILED` with `failure_reason`.
7. Every transition is written to `audit_log`.

**Journey acceptance:** end-to-end P50 ≤ 15 min at 500 docs/h sustained.

#### J-02: Escalate a stuck job (operator)

1. Operator: `GET /v1/jobs?status=STUCK&older_than=30m`.
2. Sees `correlation_id`, last audit event, SQS receive count.
3. `POST /v1/jobs/{id}/retry` → job re-queued, `attempt` incremented.
4. Audit: actor=`operator_id`, action=`JOB_RETRY`.

#### J-03: Export audit (compliance)

1. `GET /v1/audit?document_id=...&from=...&to=...`.
2. Timeline: status transitions, worker id, error codes.
3. Stage 2: export to S3 as JSON Lines + checksum.

#### J-04: DLQ incident (Platform SRE)

1. CloudWatch alarm: `ApproximateNumberOfMessagesVisible` on DLQ > 0.
2. SRE inspects messages via runbook / admin API.
3. After root-cause fix: `POST /v1/admin/dlq/replay` (Platform Admin).
4. Post-incident: audit + logs by `trace_id` / `correlation_id`.

#### J-05: Change bucket policy (Tech Lead)

1. Change only via PR to `terraform/modules/s3`.
2. CI posts `terraform plan` as a PR comment.
3. After merge — staging `apply`; production — manual approval.
4. AWS console ClickOps is forbidden without ADR and subsequent Terraform import.

---

## 3. Scope: in / out / Stages 1–3

### 3.1. In scope (cumulative across stages)

- Control-plane HTTP API (FastAPI).
- Presigned upload URLs to object storage (S3).
- Event pipeline: S3 → SQS → ECS/Fargate workers.
- PostgreSQL (RDS) — source of truth for documents, jobs, audit.
- Redis (ElastiCache) — idempotency keys, rate limits, short-lived locks.
- Status state machine with audit log.
- Terraform modules for all AWS infrastructure.
- GitHub Actions: lint/tests + terraform plan/apply gates.
- CloudWatch: logs, metrics, alarms (AWS path); local Compose: Prometheus + Grafana + Jaeger.
- Tests: pytest, moto, LocalStack (S3/SQS subset).
- Hook stubs: virus-scan, OCR, extract — fixed I/O contracts.
- Cloud ownership RACI; mandatory FinOps tags.
- Encryption at-rest / in-transit; secrets in Secrets Manager / SSM; IAM least privilege.

### 3.2. Out of scope (explicit exclusions)

| Exclusion | Reason | Possible stage |
|-----------|--------|----------------|
| Full operator portal | Separate frontend product; demo = API + metrics/traces (§13) | 2+ (thin UI optional) |
| Production OCR/ML (Textract / custom models) | Needs DS team and labeled data | 2–3 |
| Production antivirus (ClamAV / vendor) | Stage 1 = hook + stub | 2 |
| Active-active multi-region | Complexity and cost | 3 |
| Billing UI / chargeback UI | FinOps via tags/CSV in Stage 1 | 2 |
| Mobile SDK | Not in B2B API scope | out of scope |
| Blockchain ledger | Overkill; Object Lock is Stage 3 | 3 |
| PAN storage / PCI DSS scope | Not product domain | out of scope |

### 3.3. Stage 1 — MVP (8–10 weeks)

**Goal:** Replace the manual queue for one pilot tenant; prove throughput, audit completeness, and infrastructure ownership.

| Component | Deliverables |
|-----------|--------------|
| API | CRUD documents, presign, job statuses, audit read |
| Pipeline | S3 event → **ingestion** SQS → `ingestion-worker` → **processing** SQS → `processing-worker`; `stuck-scanner` polls DB for stale jobs (not on the SQS hot path) |
| Data | PostgreSQL schema v1, Alembic migrations |
| State machine | `DRAFT` → `UPLOADING` → `UPLOADED` → `QUEUED` → `SCANNING` → `EXTRACTING` → `PROCESSED` / `FAILED` / `CANCELLED` |
| Stubs | `VirusScanHook`, `OcrHook`, `ExtractHook` with contracts |
| Infrastructure | Terraform modules: S3, SQS (two work queues + DLQs + redrive), ECS Fargate, RDS, ElastiCache, IAM, ECR, ALB, KMS, CloudWatch, Secrets Manager / SSM |
| CI/CD | Ruff, mypy, pytest; terraform plan on PR; apply to staging |
| Observability | JSON logs; ≥5 CloudWatch alarms (AWS); local Prometheus/Grafana/Jaeger |
| Security baseline | Encryption at-rest/in-transit; least-privilege IAM; secrets not in git |
| Ownership | RACI signed; FinOps tags on all resources |

**Stage 1 KPI gate:** 500 docs/h sustained; 100% audit completeness; P50 latency ≤ 15 min; 100% infra changes via Terraform.

### 3.4. Stage 2 — scale and integrations (6–8 weeks)

- Workers already split (`ingestion-worker`, `processing-worker`); harden native SQS long-polling and operational separation.
- Async hot path = native SQS consumers; periodic stuck-job scanning via dedicated `stuck-scanner` (DB poll).
- Webhooks (`document.processed`, `document.failed`) with retries and HMAC signature.
- Cognito / OAuth2 client credentials.
- Real virus-scan; Textract or pluggable OCR behind the same interface.
- ADOT → X-Ray / CloudWatch EMF on the AWS path (apps export OTLP only).
- ECS autoscaling on `ApproximateNumberOfMessagesVisible`.
- Staging + production; manual approval for prod apply.
- Secrets Manager rotation.
- Optional thin demo UI (Vite + React + TypeScript) — §13; not a Stage 1 blocker.

### 3.5. Stage 3 — enterprise hardening (8–12 weeks)

- Multi-tenant hardening (schema vs row-level — ADR; row-level kept).
- Cross-region DR: S3 replication, RDS failover.
- RDS: Multi-AZ primary + **read replica** for list/audit API; status and audit writes **primary only** (Stages 2–3).
- Audit archive: S3 Object Lock (Compliance), lifecycle → Glacier.
- Search (OpenSearch — optional).
- Cost panels: Cost Explorer + `documents_processed` per tenant.
- SLA 99.9%, error budget; pen-test remediation.
- Load test: peak 5,000 docs/h.

---

## 4. Architecture

### 4.1. System context (C4 Level 1)

```
┌─────────────────┐         HTTPS          ┌──────────────────────────────────┐
│ Client systems  │ ─────────────────────► │  Document Ingestion Pipeline     │
│ (ERP, CRM,      │ ◄───────────────────── │  (AWS Cloud)                     │
│  Partner API)   │   REST + webhooks      └──────────────────────────────────┘
└─────────────────┘                                      │
┌─────────────────┐                                      │ notifications / audit
│ Back-office     │ ──── HTTPS (Stage 2 UI/API) ──► Compliance / back-office
│ operators       │
└─────────────────┘

External (Stage 2+): virus-scan provider; OCR (Textract); IdP (Cognito)
```

**Purpose:** accept documents, process them reliably asynchronously, store statuses and audit, operate infrastructure via IaC.

### 4.2. Containers (C4 Level 2)

```
                    ┌──────────────────────────────────────────────────────────────┐
                    │                        AWS Account                            │
                    │  ┌─────────────┐    ┌──────────────┐                         │
  Clients ────────► │  │ ALB         │───►│ ECS Fargate  │                         │
                    │  │             │    │ API Service  │                         │
                    │  └─────────────┘    │ (FastAPI)    │                         │
                    │                     └──────┬───────┘                         │
                    │                            │                                 │
                    │         ┌──────────────────┼─────────────────────────────────┤
                    │         ▼                  ▼                                 │
                    │  ┌────────────┐    ┌──────────────┐    ┌──────────────────┐ │
                    │  │ RDS        │    │ ElastiCache  │    │ S3 Bucket        │ │
                    │  │ PostgreSQL │    │ Redis        │    │ (documents)      │ │
                    │  └────────────┘    └──────────────┘    └────────┬─────────┘ │
                    │                                                 │ Event      │
                    │                                                 ▼            │
                    │                                          ┌────────────────┐ │
                    │                                          │ Ingestion SQS  │ │
                    │                                          │ + DLQ + redrive│ │
                    │                                          └────────┬───────┘ │
                    │                                                   │          │
                    │                     ┌─────────────────────────────┼──────┐  │
                    │                     ▼                             ▼      │  │
                    │              ┌────────────────┐            ┌────────────┐│  │
                    │              │ ECS Fargate    │            │ Processing ││  │
                    │              │ ingestion-     │───────────►│ SQS + DLQ  ││  │
                    │              │ worker         │  enqueue   └──────┬─────┘│  │
                    │              └────────────────┘                   │      │  │
                    │                                                   ▼      │  │
                    │                                            ┌────────────┐│  │
                    │                                            │ ECS        ││  │
                    │                                            │ processing-││  │
                    │                                            │ worker     ││  │
                    │                                            └────────────┘│  │
                    │              ┌────────────────┐                          │  │
                    │              │ stuck-scanner  │ (DB poll; not SQS hot)    │  │
                    │              └────────────────┘                          │  │
                    │  ┌────────────┐    ┌──────────────┐                      │  │
                    │  │ CloudWatch │    │ SSM / Secrets│                      │  │
                    │  └────────────┘    └──────────────┘                      │  │
                    └──────────────────────────────────────────────────────────────┘
```

Local Compose mirrors this split: `api`, `ingestion-worker`, `processing-worker`, `stuck-scanner`, plus LocalStack S3/SQS, Postgres, Redis, OTel Collector, Prometheus, Grafana, Jaeger.

### 4.3. Worker components (C4 Level 3)

```
ingestion-worker (SQS: document-ingestion)
    │
    ├── MessageParser (envelope, Redis idempotency)
    ├── IngestionHandler
    │       ├── S3 HeadObject (upload complete)
    │       ├── MetadataValidator (MIME / size / checksum)
    │       ├── StatusTransition → audit_log
    │       └── Enqueue PROCESS_DOCUMENT → document-processing SQS
    └── JobRepository (SQLAlchemy)

processing-worker (SQS: document-processing)
    │
    ├── MessageParser
    ├── ProcessingPipeline (hook chain)
    │       ├── VirusScanHook (stub → Stage 2)
    │       ├── OcrHook (stub → Textract)
    │       └── ExtractHook (stub → structured JSON)
    ├── JobRepository
    └── AuditLogger (append-only)

stuck-scanner (periodic DB poll)
    └── Mark / recover STUCK jobs; not on the SQS hot path
```

### 4.4. Data flow: S3 → ingestion SQS → processing SQS → workers

```
1. API creates Document (DRAFT) + Upload (expected key, checksum algorithm).
2. API issues presigned PUT → s3://{bucket}/{tenant_id}/{document_id}/{filename}.
3. Client uploads the file directly to S3.
4. S3: s3:ObjectCreated:* → document-ingestion SQS (SNS fan-out optional Stage 2).
5. ingestion-worker: long polling; visibility timeout ≥ P99 ingestion time.
6. ingestion-worker:
   a. Idempotency (Redis SET NX, TTL 24h).
   b. HEAD object — size, content-type, etag.
   c. Compare against declared MIME / max size policy.
   d. Invalid MIME → UPLOADED → FAILED + audit (do not enter SCANNING).
   e. Valid → UPLOADED → QUEUED + enqueue PROCESS_DOCUMENT on document-processing SQS.
   f. DELETE ingestion SQS message on success.
7. processing-worker:
   a. Idempotency + status checks.
   b. Transitions: QUEUED → SCANNING → EXTRACTING → PROCESSED (or FAILED).
   c. Each transition: INSERT audit_log + UPDATE documents/jobs (one transaction on worker path).
   d. DELETE processing SQS message on success (or after recording terminal FAILED — document the choice).
8. On failure: redrive → after maxReceiveCount=5 → corresponding DLQ.
9. Operator/SRE: DLQ replay after fix.
10. stuck-scanner: DB poll for stale RUNNING/QUEUED jobs; not an SQS consumer on the hot path.
```

### 4.5. AWS service selection rationale

| Service | Alternatives | Why chosen | Trade-offs |
|---------|--------------|------------|------------|
| **S3** | EFS, MinIO | 11 nines durability, presigned URLs, native events, cheap binaries | Consistency edge cases — HEAD + idempotency |
| **SQS** | Kafka (MSK), RabbitMQ on EC2 | Managed, native DLQ + redrive, IAM, pay-per-use, ideal work queue | No strict global order (FIFO per tenant evaluated Stage 2) |
| **ECS/Fargate** | Lambda, EKS | Long hooks (virus/OCR), predictable CPU/RAM, no EKS cluster tax | Task cost — offset by autoscaling |
| **RDS PostgreSQL** | DynamoDB, Aurora Serverless | Relational audit queries, status+audit transactions, SQLAlchemy maturity | Needs connection pooling (PgBouncer Stage 2); Multi-AZ + read replica below |
| **ElastiCache Redis** | DynamoDB TTL, in-memory on ECS | Sub-ms idempotency, locks, rate limits | Extra managed service (~$15–50/mo in dev) |
| **ALB** | API Gateway + Lambda | Standard FastAPI-on-ECS pattern | Fewer “API product” features than API Gateway |
| **CloudWatch** | Datadog, Grafana Cloud | Native integration without vendor on Stage 1 AWS path | Log query UX weaker — acceptable for MVP |
| **Terraform** | CDK, CloudFormation | Modules, state, team skill fit, plan in CI | Needs S3 backend + DynamoDB lock |
| **GitHub Actions** | GitLab CI, Jenkins | OIDC to AWS without long-lived keys | Minutes cost at scale |
| **Secrets Manager / SSM** | secrets in env/git | Rotation, access audit, config/secret split | Extra API call cost |

**Key principle:** control / data plane separation — FastAPI orchestrates and queries; heavy work in workers; binaries in S3; queues decouple load spikes.

**RDS: write vs read (Stages 2–3).** Production uses Multi-AZ (synchronous standby for write failover). Separately, a **read replica** serves read-heavy APIs: document lists, audit timelines, operator reports. All writes (`documents.status`, `audit_log`, jobs) go to the **primary**. RDS sharding by tenant is not introduced in Stages 1–3 — see ADR-011.

### 4.6. Failure modes and mitigations

| Failure | Symptom | Mitigation |
|---------|---------|------------|
| Worker dies mid-job | Message not deleted | Visibility timeout → redelivery; `attempt++`; DLQ |
| Duplicate S3 event | Reprocessing | Redis idempotency + current-status check |
| RDS unavailable | API 503 /ready fail | Multi-AZ in prod; alerts; graceful degradation |
| Primary RDS down | status/audit writes unavailable | Multi-AZ failover; `/ready` fails until primary recovers |
| Read replica lag | stale list/audit | lag threshold → fallback list API to primary; alert |
| DLQ growth | Alarm > 0 | Replay runbook; root cause; do not silence the alarm |
| Presigned URL expired | Client 403 from S3 | CANCELLED / re-presign |
| Invalid MIME | FAILED | Audit + clear `failure_reason` |
| Poison message | Retry loop without progress | maxReceiveCount → DLQ; alarm; triage without blocking main queue |

---

## 5. Technology stack

### 5.1. Languages and runtime

| Component | Version | Role |
|-----------|---------|------|
| Python | 3.12.x | Single language for API + workers |
| Docker | 24.x+ | Images for ECS |
| Docker Compose | 2.x | Local: API, split workers, stuck-scanner, Postgres, Redis, LocalStack, obs stack |

Local Compose image pins (not AWS targets): Postgres **16.15**, Redis **8.10** — PostgreSQL 16 line only; do not imply PG 18.

### 5.2. Application stack

| Library | Version | Role |
|---------|---------|------|
| FastAPI | 0.141.x | HTTP API, OpenAPI, dependency injection |
| Uvicorn | 0.52.x | ASGI server for API (do not pin Starlette) |
| Pydantic | v2.13.x | Request/response schemas, settings (`>=2.10,<3`) |
| SQLAlchemy | 2.0.x | ORM, async sessions (asyncpg) |
| Alembic | 1.19.x | DB migrations (`>=1.14,<2`) |
| Celery | optional; not in pyproject | Stuck-scanner is asyncio; main async = SQS |
| boto3 | 1.43.x | AWS SDK (S3, SQS, SSM, Secrets Manager) |
| httpx | 0.28.x | Outbound webhooks (Stage 2) |
| structlog | 26.x | Structured JSON logs |
| PyJWT | 2.x | JWT validation (RS256) |
| cryptography | 50.x | RS256 / key handling for JWT |
| redis-py | 8.1.x | Redis client (local image 8.10) |
| tenacity | 9.x | Retries for external hooks |
| OpenTelemetry API/SDK | 1.44.x | Traces + OTLP export |
| opentelemetry-instrumentation-fastapi | 0.65b0 | FastAPI auto-instrumentation (matched with API 1.44.x) |
| asyncpg | 0.31.x | Async PostgreSQL driver |
| uuid6 | 2025.x | UUIDv7 primary keys |

### 5.3. DevOps and quality

| Tool | Version | Role |
|------|---------|------|
| Terraform | 1.9.x | Infrastructure as code |
| AWS Provider | 5.x | AWS resources in Terraform |
| GitHub Actions | — | Continuous integration / delivery |
| Ruff | 0.8.x | Lint + format |
| mypy | 1.13.x | Static typing |
| pytest | 8.x | Tests |
| pytest-asyncio | 0.24.x | Async tests |
| moto | 5.x | AWS mocks (S3, SQS, IAM subset) |
| LocalStack | 4.14.x | Local S3/SQS (community pin `4.14.0` in Dockerfile). CalVer `2026.07.x` needs `LOCALSTACK_AUTH_TOKEN`; this repo stays on last community 4.x for Compose — no token, no Pro features. |
| pre-commit | 4.x | Local hooks |

### 5.4. AWS resources (target configuration)

| Resource | Name template | Role |
|----------|---------------|------|
| S3 | `{env}-doc-pipeline-{account_id}` | Binaries; prefix `{tenant_id}/{document_id}/` |
| S3 Event → SQS | — | Triggers ingestion queue only |
| SQS Standard | `{env}-document-ingestion` | Ingestion work queue; visibility ~300s (tune) |
| SQS DLQ | `{env}-document-ingestion-dlq` | After maxReceiveCount=5 |
| SQS Standard | `{env}-document-processing` | Processing work queue |
| SQS DLQ | `{env}-document-processing-dlq` | After maxReceiveCount=5 |
| ECS Cluster | `{env}-doc-pipeline` | Fargate |
| ECS api | `{env}-api` | FastAPI behind ALB |
| ECS ingestion-worker | `{env}-ingestion-worker` | Ingestion SQS consumers |
| ECS processing-worker | `{env}-processing-worker` | Processing SQS consumers |
| ECR | `{env}/doc-pipeline/{api,worker}` | Images |
| RDS PostgreSQL | `{env}-doc-pipeline-db` | Primary datastore |
| ElastiCache Redis | `{env}-doc-pipeline-redis` | cache.t4g.micro dev; larger prod |
| ALB | `{env}-doc-pipeline-alb` | HTTPS |
| ACM | API domain cert | TLS |
| IAM | per-service roles | Least privilege |
| SSM | `/doc-pipeline/{env}/*` | Config |
| Secrets Manager | `{env}/doc-pipeline/db` | DB credentials |
| CloudWatch Logs | `/ecs/{env}/api`, `/ecs/{env}/ingestion-worker`, `/ecs/{env}/processing-worker` | Retention 30d / 90d |
| CloudWatch Alarms | DLQ, queue age, 5xx | Paging |
| VPC | 3 AZ, private subnets | Network isolation |
| NAT Gateway | 1/AZ prod | Egress |
| Route 53 | `api.doc-pipeline.example.com` | DNS |
| KMS CMK | — | SSE S3/RDS/SQS |

### 5.5. Cost estimate and FinOps (eu-central-1, indicative)

| Service | Assumption | ~USD / month |
|---------|------------|--------------|
| S3 | 500 GB, 150k PUT, 500k GET | 15–25 |
| SQS | 5M requests | 2–5 |
| ECS Fargate | API 2×0.5 vCPU; workers 2–4×1 vCPU | 80–150 |
| RDS | db.t4g.medium Single-AZ dev; Multi-AZ prod | 50–200 |
| ElastiCache | cache.t4g.micro | 12–15 |
| NAT | 1 AZ dev | 35+ data |
| CloudWatch Logs | 20 GB ingest | 10–20 |
| Secrets Manager | 2–5 secrets | 1–3 |
| **Staging total** | | **~$200–350** |
| **Production total (Stage 2)** | autoscaling, Multi-AZ | **~$800–1500** |

**Mandatory FinOps tags:** `Project=doc-pipeline`, `Environment`, `Tenant` (where applicable), `CostCenter`, `Owner` (RACI team).

**Optimization levers:** S3 Intelligent-Tiering (Stage 2), Fargate Spot for workers (Stage 2), RDS Reserved Instances (Stage 3), right-size after two weeks of metrics. Monthly FinOps review: Cost Explorer × `documents_processed` per tenant.

---

## 6. Domain model and data schema

### 6.0. Identifier and key policy

| Entity | PK | Public ID | Composite UNIQUE / natural keys |
|--------|-----|-----------|---------------------------------|
| `tenants` | UUIDv7 | same `id` | `slug` UNIQUE |
| `documents` | UUIDv7 | same `id` (`document_id`) | **UNIQUE (`tenant_id`, `idempotency_key`)** |
| `uploads` | UUIDv7 | same `id` (`upload_id`) | — |
| `jobs` | UUIDv7 | same `id` | — |
| `audit_log` | UUIDv7 | same `id` (internal timeline API) | — |

**Rationale.** All domain entities use a single-column **UUIDv7 PK**: global uniqueness for S3 keys/API without dual-id. The dual-id pattern (BIGINT + `public_id`) is **not introduced** — write volume and join graph do not justify a second index. Composite PK `(tenant_id, id)` is forbidden: isolation is a filter + indexes `(tenant_id, …)` and UNIQUE on the natural idempotency key, not PK shape. `correlation_id` / `document_id` in logs and SQS are UUIDv7.

### 6.1. Logical ER diagram

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│   tenants   │───1:N─│  documents  │───1:N─│    jobs     │
└─────────────┘       └──────┬──────┘       └─────────────┘
                             │ 1:N
                             ▼
                      ┌─────────────┐       ┌─────────────┐
                      │  audit_log  │       │   uploads   │
                      └─────────────┘       └─────────────┘
                             ▲
                      ┌─────────────┐
                      │  job_steps  │  (Stage 2 — step detail)
                      └─────────────┘
```

### 6.2. Table `tenants`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUIDv7 | PK | |
| name | VARCHAR(255) | NOT NULL | |
| slug | VARCHAR(64) | UNIQUE, NOT NULL | URL-safe identifier |
| is_active | BOOLEAN | DEFAULT true | |
| config_json | JSONB | DEFAULT '{}' | max_file_size_mb, allowed_mime_types |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |

### 6.3. Table `documents`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUIDv7 | PK | External `document_id` |
| tenant_id | UUIDv7 | FK → tenants, NOT NULL, INDEX | Row isolation |
| document_type | ENUM | INVOICE, KYC, CONTRACT | |
| status | ENUM | see §6.7 | Current state |
| external_ref | VARCHAR(255) | NULL, INDEX | Client-side correlation |
| idempotency_key | VARCHAR(128) | UNIQUE (`tenant_id`, `idempotency_key`) | Client dedup |
| title | VARCHAR(512) | NULL | |
| metadata_json | JSONB | DEFAULT '{}' | Domain fields |
| s3_bucket | VARCHAR(255) | NULL | After upload |
| s3_key | VARCHAR(1024) | NULL | |
| file_name | VARCHAR(512) | NULL | |
| file_size_bytes | BIGINT | NULL | |
| mime_type | VARCHAR(128) | NULL | |
| checksum_sha256 | CHAR(64) | NULL | |
| processing_result_json | JSONB | NULL | Extract output |
| failure_reason | TEXT | NULL | Terminal error |
| created_by | VARCHAR(255) | NULL | JWT `sub` |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |
| processed_at | TIMESTAMPTZ | NULL | |

**Indexes:** `(tenant_id, status)`, `(tenant_id, external_ref)`, `(tenant_id, created_at DESC)`; GIN on `metadata_json` — Stage 2.

### 6.4. Table `uploads`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUIDv7 | PK | `upload_id` |
| document_id | UUIDv7 | FK → documents | |
| status | ENUM | PENDING, COMPLETED, EXPIRED, ABORTED | |
| presigned_url_issued_at | TIMESTAMPTZ | NOT NULL | |
| expires_at | TIMESTAMPTZ | NOT NULL | Default TTL 15 min |
| expected_s3_key | VARCHAR(1024) | NOT NULL | |
| completed_at | TIMESTAMPTZ | NULL | |

### 6.5. Table `jobs`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUIDv7 | PK | |
| document_id | UUIDv7 | FK, INDEX | |
| job_type | ENUM | INGESTION, PROCESSING | |
| status | ENUM | PENDING, RUNNING, SUCCEEDED, FAILED, STUCK, CANCELLED | |
| attempt | INT | DEFAULT 1 | Retry counter |
| max_attempts | INT | DEFAULT 5 | |
| sqs_message_id | VARCHAR(128) | NULL | |
| worker_id | VARCHAR(128) | NULL | ECS task ARN fragment |
| started_at / finished_at | TIMESTAMPTZ | NULL | |
| error_code | VARCHAR(64) | NULL | |
| error_message | TEXT | NULL | |
| created_at | TIMESTAMPTZ | NOT NULL | |

### 6.6. Table `audit_log` (append-only)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUIDv7 | PK | Audit event surrogate |
| tenant_id | UUIDv7 | NOT NULL, INDEX | Denormalized for queries |
| document_id | UUIDv7 | FK, INDEX | |
| job_id | UUIDv7 | FK, NULL | |
| event_type | VARCHAR(64) | NOT NULL | STATUS_CHANGED, HOOK_INVOKED, … |
| from_status / to_status | VARCHAR(32) | NULL | |
| actor_type | ENUM | USER, SYSTEM, OPERATOR | |
| actor_id | VARCHAR(255) | NULL | |
| payload_json | JSONB | DEFAULT '{}' | |
| correlation_id | UUIDv7 | NOT NULL, INDEX | |
| trace_id | VARCHAR(64) | NULL | Tracing |
| ip_address | INET | NULL | API events |
| created_at | TIMESTAMPTZ | NOT NULL, INDEX | Immutable timestamp |

**Rule:** application code must not UPDATE/DELETE `audit_log`; enforced in PostgreSQL via `REVOKE UPDATE, DELETE ON TABLE audit_log FROM PUBLIC` and a `BEFORE UPDATE OR DELETE` trigger (blocks even the table owner).

### 6.7. Document state machine

```
                    ┌──────────┐
                    │  DRAFT   │
                    └────┬─────┘
                         │ presign issued
                         ▼
                    ┌──────────┐
              ┌────│ UPLOADING │────┐
              │    └────┬─────┘    │ timeout
              │         │ S3 event │
              │         ▼          ▼
              │    ┌──────────┐  CANCELLED
              │    │ UPLOADED │
              │    └────┬─────┘
              │         ▼
              │    ┌──────────┐
              │    │  QUEUED  │◄──── retry
              │    └────┬─────┘
              │         ▼
              │    ┌──────────┐
              │    │ SCANNING │
              │    └────┬─────┘
              │         ▼
              │    ┌───────────┐
              │    │ EXTRACTING│
              │    └─────┬─────┘
         fail  │          │ success
              ▼          ▼
         ┌─────────┐  ┌───────────┐
         │ FAILED  │  │ PROCESSED │
         └─────────┘  └───────────┘
```

**Allowed transitions (domain service):**

- `DRAFT` → `UPLOADING`
- `UPLOADING` → `UPLOADED` | `CANCELLED`
- `UPLOADED` → `QUEUED` | `FAILED` (invalid MIME at ingestion)
- `QUEUED` → `SCANNING`
- `SCANNING` → `EXTRACTING` | `FAILED`
- `EXTRACTING` → `PROCESSED` | `FAILED`
- `*` → `CANCELLED` (Operator/Admin; not from terminals without an explicit rule)

Invalid transition → HTTP 409 / worker error without corrupting status.

### 6.8. Retention policy

| Entity | Hot storage | Archive |
|--------|-------------|---------|
| S3 objects | 90 days Standard | Intelligent-Tiering / Glacier — Stage 2 |
| `audit_log` | 1 year in PostgreSQL | Export to S3 — Stage 2 |
| CloudWatch logs | 30d dev, 90d prod | — |
| KYC documents | Strengthened retention up to 5 years (tenant config) | Compliance policy |

---

## 7. APIs and events

### 7.1. HTTP API conventions

- **Base URL:** `https://api.doc-pipeline.example.com/v1`
- **Authentication:** `Authorization: Bearer {JWT}`
- **Content-Type:** `application/json`
- **Idempotency:** `Idempotency-Key` header on `POST /documents`
- **Correlation:** `X-Correlation-ID` (server generates if missing)
- **Pagination:** cursor-based `?cursor=&limit=` (default 50, max 200)
- **Errors:** RFC 7807 Problem Details (`application/problem+json`)
- **OpenAPI:** live contract `/v1/openapi.json`; Swagger `/v1/docs` (disabled or VPN-only in production)

### 7.2. REST endpoints (Stage 1)

#### `POST /v1/documents` — create document metadata

**Request fields:** `document_type`, `external_ref`, `title`, `metadata`, `file_name`, `declared_mime_type`, `declared_size_bytes`.

**Response 201:** `id`, `tenant_id`, `status=DRAFT`, `document_type`, `created_at`, `correlation_id`.

#### `POST /v1/uploads/presign` — issue presigned URL

**Request:** `document_id`, `content_type`, `checksum_sha256`.

**Response 200:** `upload_id`, `presigned_url`, `method=PUT`, `expires_at`, `s3_bucket`, `s3_key`, `required_headers` (Content-Type, checksum, SSE-KMS).

**Policy:** TTL 15 min (max 60 via tenant config); max size via bucket policy / conditions; SSE-KMS required.

#### `GET /v1/documents/{document_id}` — document + job summary + last 5 audit events

#### `GET /v1/documents` — filters: `status`, `document_type`, `external_ref`, dates, cursor

#### `GET /v1/jobs/{job_id}`, `GET /v1/jobs` — filters: `status`, `document_id`, `older_than`

#### `POST /v1/jobs/{job_id}/retry` — Operator; for `FAILED` / `STUCK`

#### `POST /v1/jobs/{job_id}/cancel` — Operator/Admin

#### `GET /v1/audit` — requires `document_id`; optional `from`, `to`, `event_type`

#### `GET /v1/health` — liveness; `GET /v1/ready` — readiness (PostgreSQL + Redis)

#### `POST /v1/admin/dlq/replay` — Platform Admin; body: list of message IDs

### 7.3. HTTP status codes

| Code | Use |
|------|-----|
| 201 / 200 | Created / OK |
| 400 | Business-rule validation error |
| 401 / 403 | Unauthorized / Forbidden (RBAC) |
| 404 | Not found in tenant scope (including foreign tenant IDs — anti-enumeration) |
| 409 | Invalid status transition / idempotency conflict |
| 422 | Pydantic schema error |
| 429 | Rate limit (Redis) |
| 500 / 503 | Internal error / dependency unavailable |

### 7.4. SQS message contract (S3 event → ingestion)

**Queue:** `{env}-document-ingestion`

Logical envelope fields: `schema_version`, `event_source=aws:s3`, `event_name`, `event_time`, `bucket`, `object_key`, `object_size`, `etag`, `correlation_id`, `tenant_id`, `document_id`.

**Stage 1:** `tenant_id` and `document_id` are parsed from the object key; `correlation_id` is loaded from the DB (stored at presign). SQS message attributes (`tenant_id`, `document_type`, `trace_id`) support filtering/routing.

### 7.5. Internal processing message

Type `PROCESS_DOCUMENT` on `{env}-document-processing`: `job_id`, `document_id`, `tenant_id`, `document_type`, `s3_bucket`, `s3_key`, `attempt`, `correlation_id`, `requested_hooks`.

### 7.6. Hook contracts (interfaces / stubs, no code)

Hooks are **pluggable stages** with fixed contracts. Stage 1 ships stubs; production implementations plug in without breaking the state machine.

| Hook | Input | Success | Failure |
|------|-------|---------|---------|
| VirusScanHook | bucket, key, mime | `{ clean: true, scanner, scan_id }` | `clean=false` → `FAILED` |
| OcrHook | same | `{ provider, pages, text_preview, confidence }` | provider error → retry / FAILED |
| ExtractHook | document type + OCR | typed JSON (invoice/kyc/contract) | → FAILED |

**Stub contract rules:**

- deterministic output for demos and tests (by `document_id` / checksum);
- same fields as production implementations;
- failures modeled via config (`stub_virus_clean=false` → FAILED);
- duration simulated (sleep with jitter) for realistic visibility timeouts.

**Stage 2:** ClamAV sidecar / vendor API; Textract or other OCR behind the same interface.

### 7.7. Webhooks (Stage 2)

Events: `document.processed`, `document.failed`. Signature: HMAC-SHA256 in `X-Webhook-Signature`. Fields: `event_id`, `event_type`, `occurred_at`, `tenant_id`, `data` (document_id, status, external_ref, processing_result).

---

## 8. Non-functional requirements

### 8.1. Performance and scalability

| Requirement | Target |
|-------------|--------|
| API p95 read | ≤ 200 ms |
| API p95 write | ≤ 500 ms |
| Concurrent API requests | 200 RPS (horizontal, Stage 2) |
| Worker parallelism | Autoscale 2–20 tasks by queue depth |
| Max object size | 50 MB default (up to 100 MB via tenant config) |
| Presigned URL generation | ≤ 100 ms p95 |

### 8.2. Availability and reliability

| Requirement | Implementation |
|-------------|----------------|
| API availability | Multi-AZ ECS, minimum 2 tasks in production |
| RDS | Multi-AZ prod; 7-day backups; **read replica** for list/audit API (Stages 2–3); writes primary only |
| At-least-once | Redis idempotency + DB UNIQUE / status checks |
| Retry | Visibility timeout; maxReceiveCount=5 → DLQ (redrive policy) on **both** work queues |
| Poison messages | DLQ alarm + replay runbook |
| Graceful shutdown | SIGTERM: finish in-flight or return message to queue |

### 8.3. Security

| Area | Requirement |
|------|-------------|
| IAM least privilege | Separate roles: `api-task-role`, `ingestion-worker-task-role`, `processing-worker-task-role`, `github-oidc-deploy-role`; no `*` on S3/SQS outside scoped ARNs |
| Encryption at-rest | S3 SSE-KMS; RDS encrypted; ElastiCache at-rest; SQS SSE |
| Encryption in-transit | TLS 1.2+; RDS force SSL |
| Secrets | Not in git; SSM Parameter Store (non-secret) / Secrets Manager (DB credentials); rotation Stage 2 |
| Network | ECS/RDS/Redis in private subnets; only ALB public |
| Input | Strict Pydantic; MIME allowlist; filename sanitization |
| Audit | All status changes; append-only |
| Vulnerabilities | ECR scan on push; Dependabot |
| Rate limiting | Redis token bucket: 100 req/min per tenant (Stage 1) |

### 8.4. IAM matrix (summary)

| Principal | S3 | SQS | RDS | Redis | SSM/Secrets |
|-----------|----|-----|-----|-------|-------------|
| api-task-role | Presign / limited object access | SendMessage (optional) | RW via SG | RW | Read config |
| ingestion-worker-task-role | GetObject, HeadObject | Receive/Delete/ChangeVisibility on ingestion; SendMessage on processing | RW | RW | Read secrets |
| processing-worker-task-role | GetObject, HeadObject | Receive/Delete/ChangeVisibility on processing | RW | RW | Read secrets |
| github-oidc-role | Manage resources via Terraform (scoped) | | | | |

### 8.5. Observability

| Signal | Tool | Requirements |
|--------|------|--------------|
| Logs | CloudWatch Logs (AWS); structlog JSON (all) | JSON: timestamp, level, service, correlation_id, tenant_id, document_id, event |
| Metrics | CloudWatch (AWS); Prometheus (local) | `documents_processed`, `hook_duration_ms`, queue age |
| Alarms | CloudWatch / Prometheus | DLQ > 0; queue age > 10 min; API 5xx > 1%; RDS CPU > 80% |
| Tracing | Local: **Jaeger** via OTel Collector; AWS: ADOT → X-Ray | `trace_id` in audit when available |
| Dashboard | CloudWatch Dashboard / Grafana | Throughput, latency proxies, errors, cost proxy |

Apps export **OTLP only** to the collector. Local backends: Prometheus + Grafana + **Jaeger** (not Tempo). AWS path: ADOT → CloudWatch EMF + X-Ray.

**Required log fields:** `timestamp`, `level`, `service`, `environment`, `message`, `correlation_id`, `tenant_id`, `document_id`, `job_id`, and on status change — `from_status` / `to_status`, `duration_ms`. Secrets and full presigned URLs must never be logged.

Metric attributes use low-cardinality labels (`tenant_slug`, `document_type`, `status`, `hook`) — never `document_id` / `correlation_id`.

### 8.6. Compliance and data residency

- Store data in `eu-central-1` (GDPR alignment).
- Right to erasure: `DELETE /v1/documents/{id}` — Stage 2 (soft-delete + S3 purge runbook).
- KYC: strengthened audit retention up to 5 years (tenant config).

### 8.7. Disaster recovery (Stage 3)

| Metric | Target |
|--------|--------|
| RPO | 15 min (S3 replication + RDS snapshots) |
| RTO | 60 min (terraform apply DR + DNS failover) |

### 8.8. Production-ready checklist (required for Stage 1)

| # | Requirement | Spec location |
|---|-------------|---------------|
| 1 | Idempotent workers + UNIQUE / Redis | §4.4, §8.2 |
| 2 | Redrive policy, DLQ, replay runbook | §3, §7.2, §8.2 |
| 3 | Encryption at-rest and in-transit | §8.3 |
| 4 | Secrets in Secrets Manager / SSM, not git | §5.4, §8.3 |
| 5 | IAM least privilege + separate task roles | §8.4, Appendix A |
| 6 | Structured logs + metrics + alarms | §8.5, Appendix B |
| 7 | Terraform modules + plan/apply CI gates | §9, §10.4 |
| 8 | FinOps tags + cost estimate | §5.5 |
| 9 | Health checks + graceful shutdown | §7.2, §8.2 |
| 10 | Cloud ownership RACI | §12 ADR-008 |
| 11 | Hook contracts virus-scan / OCR / extract | §7.6 |
| 12 | Demo without mandatory UI: API + metrics/traces | §13 |

---

## 9. Repository structure

```
doc-pipeline/
├── README.md
├── AGENTS.md
├── spec.md                         # this product SoT (English)
├── pyproject.toml
├── docker-compose.yml              # api, ingestion-worker, processing-worker,
│                                   # stuck-scanner, postgres, redis, localstack,
│                                   # otel-collector, prometheus, grafana, jaeger
├── docker-compose.test.yml
├── .pre-commit-config.yaml
├── .github/workflows/
│   ├── ci.yml
│   ├── integration.yml
│   ├── terraform-plan.yml
│   ├── terraform-apply-staging.yml
│   └── terraform-apply-prod.yml
├── terraform/
│   ├── backend.tf                  # S3 state + DynamoDB lock
│   ├── versions.tf
│   ├── modules/
│   │   ├── networking/             # VPC, subnets, NAT, SG
│   │   ├── s3/
│   │   ├── sqs/                    # ingestion + processing queues + DLQs + redrive
│   │   ├── ecs/
│   │   ├── rds/
│   │   ├── elasticache/
│   │   ├── alb/
│   │   ├── iam/                    # roles, OIDC
│   │   ├── ecr/
│   │   ├── cloudwatch/
│   │   ├── kms/
│   │   └── secrets/                # Secrets Manager / SSM params
│   └── environments/{dev,staging,prod}/
├── src/doc_pipeline/
│   ├── main.py
│   ├── config/settings.py
│   ├── api/v1/                     # documents, uploads, jobs, audit, health
│   ├── domain/                     # models, schemas, services, state_machine
│   ├── infrastructure/             # aws, db, cache
│   ├── worker/                     # consumers, handlers, hooks, stuck_scanner
│   └── migrations/                 # Alembic (or top-level alembic/)
├── tests/{unit,integration,fixtures}/
├── scripts/
├── docs/
│   ├── adr/
│   ├── runbooks/
│   ├── ownership-raci.md
│   ├── plans/
│   ├── agentic/
│   └── openapi/
└── deploy/{Dockerfile.api,Dockerfile.worker}
```

Do **not** duplicate this specification as `TZ.md`.

---

## 10. Testing strategy and CI/CD

### 10.1. Test pyramid

| Level | Scope | Tools | Coverage goal |
|-------|-------|-------|---------------|
| Unit | state machine, schemas, services, hook stubs | pytest | ≥ 80% domain/services |
| Integration | API + PostgreSQL | pytest-asyncio, compose/testcontainers | Critical paths |
| AWS integration | Presign, SQS, event flow, redrive | moto 5.x, LocalStack 4.14.x | Ingestion pipeline |
| Contract | OpenAPI | schemathesis (Stage 2) | Public endpoints |
| Load | 500–5000 docs/h | k6 / Locust (Stage 2+) | Before production |

### 10.2. moto and LocalStack

| Service | moto | LocalStack | Choice |
|---------|------|------------|--------|
| S3 | solid | yes | moto primary (faster) |
| SQS | yes | yes | moto unit; LocalStack E2E in compose |
| IAM | partial | yes | moto unit; real policies via terraform validate |
| ECS | no | partial | Mock consumer in integration |

### 10.3. Mandatory scenarios

1. Happy path: create → presign → upload (mock) → ingestion SQS → processing → `PROCESSED`.
2. Idempotency: duplicate SQS → single `PROCESSED` outcome.
3. Invalid MIME → `FAILED` + audit (from `UPLOADED`, not via `SCANNING`).
4. Virus stub `clean=false` → `FAILED`.
5. Invalid status transition → 409.
6. After 5 failures — message in DLQ (redrive) on the relevant queue.
7. Tenant A ≠ tenant B isolation → 404 for foreign IDs.
8. Upload after TTL → CANCELLED / re-presign.
9. Terraform plan has no unexpected destroy on a typical PR (policy check).

### 10.4. GitHub Actions pipelines

| Workflow | Trigger | Contents |
|----------|---------|----------|
| `ci.yml` | PR | Ruff, mypy, unit (≥80%), docker build |
| `integration.yml` | PR + main | postgres, redis, localstack → integration tests |
| `terraform-plan.yml` | PR (terraform/) | OIDC → init/validate/plan → PR comment |
| `terraform-apply-staging.yml` | push main | staging apply + smoke `/health`, `/ready` |
| `terraform-apply-prod.yml` | workflow_dispatch | reviewers → plan → apply → smoke + rollback link |

### 10.5. Quality gates

| Gate | When | Blocking |
|------|------|----------|
| Ruff | PR | Yes |
| mypy | PR | Yes (from sprint 2) |
| Unit ≥80% | PR | Yes |
| Integration | PR | Yes |
| Terraform validate/plan | PR when TF changes | Yes; destroy/replace requires review |
| Staging smoke | merge to main | Yes |
| Prod approval | release | Yes |

### 10.6. Branching

- `main` → auto-deploy to staging  
- tags `v*` / `release/*` → production  
- feature branches → PR into `main`

---

## 11. Acceptance criteria

Expectation level: Middle+/Senior (audit completeness, IAM, IaC gates, failure modes, demo without magic, RACI).

### 11.1. Feature-level DoD

- [ ] User-story acceptance criteria verified by QA.
- [ ] API reflected in live OpenAPI (`/v1/docs`).
- [ ] Unit tests; coverage not reduced.
- [ ] Integration of happy path if pipeline touched.
- [ ] Structured logging with `correlation_id` on new paths.
- [ ] Audit on all status transitions.
- [ ] RBAC + tenant isolation tested.
- [ ] Ruff + mypy green.
- [ ] No unresolved critical/high Dependabot findings.
- [ ] Terraform changes include plan in PR.
- [ ] Runbook updated when operability changes.
- [ ] FinOps tags on new resources.

### 11.2. Stage 1 release DoD

- [ ] Load-test report 500 docs/h (30 min sustained).
- [ ] P50 latency ≤ 15 min documented.
- [ ] 100% audit completeness — integrity autotest.
- [ ] DLQ alarm fire drill.
- [ ] IAM least-privilege checklist signed.
- [ ] Encryption verified: S3, RDS, SQS, Redis.
- [ ] Secrets only in Secrets Manager / SSM.
- [ ] Redrive policy and DLQs confirmed by test.
- [ ] Hook contracts (virus/OCR/extract) covered by stub unit tests.
- [ ] Operator demo 8–10 min (API + metrics/traces + IaC, see §13).
- [ ] Pilot tenant onboarded.
- [ ] FinOps tags on all resources; cost note in README.
- [ ] RACI ownership signed by Tech Lead + Platform Lead.
- [ ] Security review: presign scope; no public buckets.
- [ ] Rollback: previous ECS task definition + terraform state procedure.

### 11.3. Operational readiness

- [ ] Dashboard URL in runbook (CloudWatch and/or Grafana).
- [ ] On-call (formal paging — Stage 2).
- [ ] DLQ replay script / API verified on staging.
- [ ] One-step Alembic rollback verified.
- [ ] Secrets do not leak to logs (scrubbing verified).

---

## 12. Architecture decisions and FAQ

Format: decision → alternatives → why → trade-off. Cloud ownership and IaC gates are first-class product concerns.

### ADR-001. S3 → SQS, not a direct Lambda trigger

| | |
|--|--|
| **Decision** | S3 events land on SQS; Fargate workers consume the queues |
| **Alternatives** | S3 → Lambda directly; S3 → SNS → Lambda; Kafka only |
| **Why** | Buffer for scale-out; native DLQ + redrive; replay; long hooks beyond Lambda limits |
| **Trade-off** | Another managed service; no strict order without FIFO |

### ADR-002. At-least-once + idempotency (not exactly-once)

| | |
|--|--|
| **Decision** | Rely on SQS semantics; Redis `SET NX` + UNIQUE/status checks in DB |
| **Alternatives** | Kafka exactly-once / transactional outbox end-to-end |
| **Why** | Sufficient for a document work queue; simpler and cheaper than MSK |
| **Trade-off** | Idempotency discipline required in all handlers |

### ADR-003. State machine and audit in PostgreSQL

| | |
|--|--|
| **Decision** | Document status and `audit_log` in RDS; status + audit in one transaction (worker path and job retry/cancel HTTP) |
| **Alternatives** | Events only in S3/logs; DynamoDB single-table |
| **Why** | Compliance queries, SQL, transition integrity |
| **Trade-off** | RDS load; pooling needed at scale |

### ADR-004. Presigned upload, not multipart through the API

| | |
|--|--|
| **Decision** | Client uploads directly to S3 via temporary URL |
| **Alternatives** | `POST` file to FastAPI; multipart via API Gateway |
| **Why** | Scale, API traffic cost, no ALB body limits |
| **Trade-off** | Client must PUT to S3; TTL and conditions must be controlled |

### ADR-005. Stub hooks with interfaces

| | |
|--|--|
| **Decision** | `VirusScanHook` / `OcrHook` / `ExtractHook` with Stage 1 stubs |
| **Alternatives** | Textract + ClamAV in MVP |
| **Why** | Unblocks integrations and audit without DS/security vendor; contract fixes replacement |
| **Trade-off** | “Smart” processing demo deferred; stub contract must be realistic |

### ADR-006. ECS/Fargate instead of Lambda-only or EKS

| | |
|--|--|
| **Decision** | API and workers on Fargate (`api`, `ingestion-worker`, `processing-worker`) |
| **Alternatives** | Lambda-only; EKS |
| **Why** | Hook duration, persistent connections, predictable container runtime without EKS cluster tax |
| **Trade-off** | Task cost must be right-sized |

### ADR-007. Terraform + OIDC as the only infra change path

| | |
|--|--|
| **Decision** | 100% of resources in Terraform modules; ClickOps forbidden without ADR; CI via GitHub OIDC |
| **Alternatives** | Console + CloudFormation; long-lived IAM users for CI |
| **Why** | Reproducibility, plan review, no secrets in CI |
| **Trade-off** | Module ramp-up cost; remote state care |

### ADR-008. Cloud resource ownership (RACI)

| Resource / process | Responsible (R) | Accountable (A) | Consulted (C) | Informed (I) |
|--------------------|-----------------|-----------------|---------------|--------------|
| S3 bucket policy / lifecycle | Platform SRE (`terraform/modules/s3`) | Platform Lead | Backend | FinOps |
| SQS + DLQ + redrive (both queues) | Platform SRE | Platform Lead | Backend | On-call |
| ECS task definitions / services | Backend + SRE jointly | Platform Lead | QA | PO |
| RDS schema / Alembic migrations | Backend | Tech Lead | SRE (capacity) | Compliance |
| IAM roles / policies | Platform SRE | Platform Lead | Security | Backend |
| CloudWatch / Grafana alarms & panels | SRE (primary), Backend (secondary) | Platform Lead | PO | On-call |
| DLQ monitoring and replay | SRE on-call | Incident Commander | Backend | Compliance |
| FinOps tags and monthly review | FinOps Analyst | FinOps Lead | SRE | PO |
| Terraform state backends | Platform SRE | Platform Lead | — | Security |
| Secrets rotation (Secrets Manager) | SRE | Security | Backend | Platform Lead |
| Hook contracts virus/OCR/extract | Backend | Tech Lead | DS (Stage 2) | PO |
| Terraform plan/apply CI gates | Platform SRE | Platform Lead | Backend | QA |

**Ownership rule:** the platform team owns S3/SQS/IAM via Terraform modules; changes go through PR + plan gate only; the application never “fixes” bucket policy in the console.

### ADR-009. Demo without mandatory UI

| | |
|--|--|
| **Decision** | Stage 1 demo via OpenAPI (`/v1/docs`) + metrics/traces + DLQ runbook (see §13) |
| **Alternatives** | Mandatory admin UI in MVP |
| **Why** | Product value is a reliable cloud pipeline and AWS ownership; UI does not close Stage 1 KPIs |
| **Trade-off** | Operators less convenient until Stage 2; compensated by jobs/audit APIs |

### ADR-010. Secrets Manager + SSM, not env in task definition

| | |
|--|--|
| **Decision** | Non-secret config → SSM Parameter Store; DB secrets → Secrets Manager; inject into ECS task |
| **Alternatives** | Plain env in Terraform state / git; HashiCorp Vault |
| **Why** | Native AWS integration, access audit, Stage 2 rotation readiness |
| **Trade-off** | Extra IAM read permissions; cold-start latency minimal |

### ADR-011. RDS replication instead of sharding

| | |
|--|--|
| **Decision** | Multi-AZ primary for write HA; read replica for audit/list API; PostgreSQL sharding out of Stages 1–3 |
| **Alternatives** | Shard by `tenant_id`; DynamoDB single-table; Aurora Serverless without explicit replica |
| **Why** | Bottleneck is read-heavy list/audit and compliance queries, not single-primary write saturation at pipeline scale; status+audit transactions are simpler on one primary |
| **Revisit when** | Sustained primary **write** saturation (WAL/IOPS) after PgBouncer + replica; cross-tenant hot partitions |

### ADR-012. Identifier policy (UUIDv7, no dual-id)

| | |
|--|--|
| **Decision** | All domain entities (`tenants`, `documents`, `uploads`, `jobs`, `audit_log`) use **UUIDv7 PK**; `UNIQUE (tenant_id, idempotency_key)` on documents; dual-id and composite PK `(tenant_id, id)` are not used |
| **Alternatives** | UUIDv4 (`gen_random_uuid()`); dual-id BIGINT+`public_id`; composite PK for multi-tenancy |
| **Why UUIDv7** | Better B-tree insert locality vs random v4; convenient API/S3 keys without a second identifier |
| **Why no dual-id** | No write-heavy financial contour; second index and two IDs in ORM/logs are not justified |
| **Why no `(tenant_id, id)` PK** | Isolation = filter + UNIQUE/indexes; composite PK complicates FKs and `document_id` in SQS without authz gain |
| **Trade-off** | Eventual consistency on list/audit via replica; monitor `ReplicaLag` |

### Short FAQ

1. **Why not Kafka?** A document work queue does not need log compaction or fan-out to hundreds of consumers; SQS is cheaper and simpler with DLQ.
2. **Why Redis if we have a DB?** Sub-ms locks/idempotency on the worker hot path; the DB remains the status source of truth.
3. **Why Standard SQS, not FIFO?** Throughput and cost; per-document order is enforced by the state machine, not global FIFO.
4. **Why append-only audit?** Compliance and investigations; UPDATE/DELETE destroy evidentiary value.
5. **Why stub OCR?** MVP proves ingestion, statuses, IAM, IaC; ML is a separate stream with data and quality metrics.
6. **Why RACI in the product spec?** Production outages need a clear owner for S3/DLQ/IAM; without a matrix, ownership is ambiguous.

---

## 13. Thin demo UI (product decision)

### 13.1. Decision

**Stage 1 does not require a thin UI.** Product value is demonstrated via:

1. **OpenAPI / Swagger (live `/v1/docs`)** — create document, presign, poll status, audit, retry.
2. **Metrics and traces** — local Grafana/Prometheus/Jaeger; AWS CloudWatch + ADOT/X-Ray — throughput, queue age, API errors, DLQ depth.
3. **DLQ replay runbook** — SRE operational scenario without a UI button.

### 13.2. Rationale

| Argument | Explanation |
|----------|-------------|
| Product value | Reliable cloud pipeline, IAM, IaC, DLQ, audit — not a table UI |
| Stage 1 KPIs | Throughput, latency, audit completeness measured by metrics and API |
| Cost | Admin UI is a separate product; distracts MVP from control/data plane |
| Operator path | Jobs/audit APIs cover triage until Stage 2 UX |

### 13.3. How to demo without UI

1. Walk the request chain in OpenAPI (or `httpie`/`curl`).
2. Open logs / Jaeger by `correlation_id`.
3. Show Grafana or CloudWatch: `documents_processed`, SQS visible/age, 5xx.
4. Induce a failure (virus stub `clean=false` or synthetic poison) → DLQ alarm.
5. Briefly walk `docs/runbooks/dlq-replay.md` and admin replay API.
6. Show `docs/ownership-raci.md` and a terraform plan PR comment.

### 13.4. Optional thin UI (Stage 2+, non-blocker)

If operator convenience is needed later — **only** a thin, mostly read UI:

| Screen | Goal | What UI must not do |
|--------|------|---------------------|
| Document list | Filter by status/type/tenant | Store files or run OCR |
| Document card | Status, audit timeline, job link | Bypass API state machine |
| Stuck jobs | List + Retry/Cancel | Call backend API only; no client business logic |
| DLQ overview (Platform Admin) | Depth + replay | “Fix” IAM/Terraform |

**UI stack (if added, Stage 2+):** Vite + React + TypeScript SPA; calls only the FastAPI OpenAPI; no HTMX/server-rendered admin as the primary path and no separate BFF zoo. All business logic stays on FastAPI.

**Bottom line:** Stage 1 is proven by **API + metrics/traces + IaC**; thin UI improves operator UX, it does not prove the architecture.

---

## 14. Product positioning and non-goals

### 14.1. Gaps this platform closes vs typical document queues

| Typical gap | How the Pipeline closes it |
|-------------|----------------------------|
| Manual document queue | SQS + state machine + operator retry |
| No status audit trail | Append-only `audit_log` + correlation |
| ClickOps infrastructure | 100% Terraform modules + plan/apply gates |
| No owner for S3/DLQ/IAM | RACI §12 ADR-008 |
| No poison-message strategy | DLQ + redrive + alarm + replay runbook |
| OCR/virus “later somehow” | Hook interface + stubs with contracts |
| No AWS-path test story | moto + LocalStack + CI integration |
| Invisible cost | FinOps tags + cost notes §5.5 |
| Presign “by feel” | TTL, SSE-KMS, bucket conditions, security DoD |
| Secrets in git / env | Secrets Manager + SSM |
| Demo = UI screenshot | Demo = API + metrics/traces + IaC (§13) |

### 14.2. Distinction from “another FastAPI CRUD”

- Explicit control plane / data plane separation.
- Production SQS patterns: visibility, DLQ, redrive, idempotency; **two** work queues with split workers.
- Cloud ownership as a first-class theme (not “infra later”).
- Compliance mindset: audit, retention, tenant isolation (foreign ID → 404).
- Pluggable processing without pretending stubs are production ML.
- FinOps and security baseline from day one.

### 14.3. Non-goals (honest boundaries)

- Production OCR/ML accuracy — Stage 2+ with a data/science track.
- Active-active multi-region — Stage 3.
- Full operator portal — not a Stage 1 Must (thin UI optional later).
- SOC2 certification — not Stage 1, but audit is designed with compliance in mind.
- Stage 1 virus-scan / OCR stubs are **not** production AV/OCR.

---

## Appendices

### A. Least-privilege IAM checklist (Stage 1)

- [ ] No `Action: "*"` on task roles.
- [ ] S3 ARNs scoped to bucket/env prefixes.
- [ ] Workers lack broad `s3:PutObject` (upload is client via presign).
- [ ] API lacks `sqs:DeleteMessage` (unless an admin path).
- [ ] OIDC role scoped to the environment Terraform resource set.
- [ ] Secrets only via Secrets Manager / SSM SecureString.
- [ ] No long-lived access keys in GitHub Secrets.

### B. Minimum CloudWatch / Prometheus alarm set

1. DLQ `ApproximateNumberOfMessagesVisible` > 0 (ingestion **and** processing DLQs).
2. Work queues: age of oldest message > 10 min.
3. API 5xx rate > 1% (5 min).
4. RDS CPU > 80% (10 min).
5. ECS: worker tasks running = 0 while queue depth > 0.

### C. FinOps checklist (Stage 1)

- [ ] Tags `Project`, `Environment`, `CostCenter`, `Owner` on all resources.
- [ ] Cost note in README with indicative $/month.
- [ ] Proxy metric `documents_processed` for unit economics.
- [ ] Monthly FinOps review process documented.

### D. Document changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-06-15 | First commercial specification |
| 2.0 | 2026-06-15 | Glossary, ADR summaries, API+observability demo path |
| 3.0 | 2026-06-15 | Full rewrite: stages, production-ready checklist, RACI, Secrets Manager/SSM, redrive/DLQ, FinOps, hook contracts |
| 3.1 | 2026-06-28 | English product SoT; appendix removed from spec; architecture aligned with split workers (two SQS work queues + DLQs, `ingestion-worker` / `processing-worker` / `stuck-scanner`); known GAPs qualified; local obs = Jaeger |

---

**End of document**

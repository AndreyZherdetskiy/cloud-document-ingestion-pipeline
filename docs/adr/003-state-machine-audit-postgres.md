# ADR-003: State machine and audit in PostgreSQL

- **Status:** Accepted
- **Date:** 2026-06-15
- **Spec refs:** §6.6–6.7, §12 ADR-003

## Context

Compliance and operator investigations need a durable status timeline correlated across API, SQS, and worker. Logs alone are insufficient as a proof trail.

## Decision

Document status and `audit_log` live in **PostgreSQL (RDS)**. Every status change and its audit row commit in **one transaction**. `audit_log` is **append-only**; application code must not UPDATE/DELETE it; worker DB role omits DELETE.

## Consequences

- SQL-friendly compliance export and transition integrity.
- RDS load and connection pooling matter as volume grows.
- CloudWatch logs remain for ops; `audit_log` is the regulator/dispute trail.

## Amendment (2026-06-15)

Stage 1 worker intake may use `UPLOADED → FAILED` (and unused `QUEUED → FAILED`) for **invalid MIME** before hooks run. Spec §6.7 lists `FAILED` only from `SCANNING` / `EXTRACTING`; spec §4.6 requires MIME failure → `FAILED` without implying a virus-scan stage. Routing MIME failure through `SCANNING` would mis-label the audit trail. `CANCELLED` remains allowed from non-terminal statuses.

## Alternatives considered

- Events-only in S3/logs — weak integrity and queryability.
- DynamoDB single-table — worse fit for relational status+audit joins in Stage 1.

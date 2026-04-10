# ADR-012: UUIDv7 primary keys, no dual-id

- **Status:** Accepted
- **Date:** 2026-04-09
- **Spec refs:** §6.0, §12 ADR-012

## Context

Neighboring products use BIGINT identity + `public_id` dual-id for write-heavy financial or partner graphs. This pipeline needs globally unique IDs for API and S3 keys without a second index tax.

## Decision

All domain entities (`tenants`, `documents`, `uploads`, `jobs`, `audit_log`) use a single-column **UUIDv7 PK**. API `id` **is** that UUID. Natural UNIQUE `(tenant_id, idempotency_key)` on documents. **No dual-id**, no BIGINT identity, no composite PK `(tenant_id, id)`. Tenant isolation is filter + indexes, not PK shape.

## Consequences

- Better B-tree insert locality than random UUIDv4; one ID in ORM, logs, and OpenAPI.
- Do not invent `public_id` fields or sequential ids in DTOs.
- Reviewer rejects dual-id copy-paste from Hub/billing.

## Alternatives considered

- UUIDv4 (`gen_random_uuid()`) — worse index locality.
- Dual-id BIGINT + `public_id` — unjustified second index for this domain.
- Composite `(tenant_id, id)` PK — complicates FKs and SQS `document_id` without authz gain.

# ADR-014: Multi-tenant hardening stays row-level

- **Status:** Accepted
- **Date:** 2026-04-10
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

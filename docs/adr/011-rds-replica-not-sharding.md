# ADR-011: RDS replica scaling, not sharding

- **Status:** Accepted
- **Date:** 2026-04-09
- **Spec refs:** §3.5, §12 ADR-011

## Context

List/audit APIs and compliance queries are read-heavy. Sharding PostgreSQL by `tenant_id` would complicate status+audit transactions without Stage 1–3 evidence of write saturation.

## Decision

**No RDS sharding in Stages 1–3.** Use Multi-AZ primary for write HA (as environments mature) and a **read replica** for list/audit reads in Stage 2–3. Status and audit **writes only on primary**.

## Consequences

- Simpler transactions and FK model for the state machine.
- Eventual consistency on replica reads; monitor replica lag.
- Revisit sharding only if primary write path saturates after pooling + replica.

## Alternatives considered

- Shard by `tenant_id` — premature; complicates FK and transactions.
- DynamoDB single-table — poor fit for relational audit/timeline Stage 1.
- Aurora Serverless without an explicit replica story — does not replace the decision to keep writes on one primary.

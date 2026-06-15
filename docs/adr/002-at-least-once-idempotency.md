# ADR-002: At-least-once delivery with idempotency

- **Status:** Accepted
- **Date:** 2026-06-15
- **Spec refs:** §4.4, §8.2, §12 ADR-002

## Context

SQS and S3 event delivery can duplicate messages. Stakeholders often ask for “exactly-once”; end-to-end exactly-once across S3/SQS/workers is not free and is unnecessary for this work queue.

## Decision

Accept **at-least-once** semantics. Idempotency via Redis `SET NX` plus database UNIQUE / status checks before transitions. Handlers must be safe under replay. No exactly-once claim in docs or metrics.

## Consequences

- Duplicate SQS deliveries must yield a single `PROCESSED` outcome without double side effects.
- Every handler needs explicit idempotency discipline.
- Kafka EOS / transactional outbox end-to-end is out of Stage 1–3 Must.

## Alternatives considered

- Kafka exactly-once / transactional outbox e2e — higher cost and ops than required for document work queues.
- Ignoring duplicates — risk of double processing and broken audit.

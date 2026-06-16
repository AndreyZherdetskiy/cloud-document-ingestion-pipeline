# ADR-009: Stage 1 demo without mandatory UI

- **Status:** Accepted
- **Date:** 2026-06-15
- **Spec refs:** §13, §12 ADR-009

## Context

Stage 1 KPIs are throughput, audit completeness, IAM/IaC, and DLQ operability. A mandatory admin portal would consume capacity without proving the cloud pipeline.

## Decision

**Stage 1 demo does not require UI.** Demonstrate via OpenAPI (`/v1/docs`), LocalStack/CloudWatch (or local Grafana/Jaeger), and DLQ runbook/admin replay API. Optional thin Vite+React+TS UI is Stage 2+ and talks only to the API.

## Consequences

- Stage 1 focuses on control/data plane, worker, Terraform, and observability.
- Operators rely on API jobs/audit until Stage 2 UX.
- Fake “portal” stubs are out of scope for Stage 1.

## Alternatives considered

- Mandatory admin UI in MVP — distracts from pipeline KPIs; deferred.

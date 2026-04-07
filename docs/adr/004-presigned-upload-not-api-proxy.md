# ADR-004: Presigned upload, not API file proxy

- **Status:** Accepted
- **Date:** 2026-04-07
- **Spec refs:** §4.1–4.2, §7, §12 ADR-004

## Context

Large invoices/KYC/contracts would exhaust API body limits, inflate ALB/API cost, and blur control vs data plane if streamed through FastAPI.

## Decision

API is **control plane only**. Clients upload via **S3 presigned PUT** URLs. The API never proxies file bytes as the main path. Presign sets TTL, key prefix, Content-Type, and SSE conditions.

## Consequences

- Scales with S3 throughput; API stays thin.
- Clients must speak S3 PUT; TTL expiry and condition mismatches need clear API errors / re-presign.
- Security review focuses on presign conditions and no public bucket.

## Alternatives considered

- `POST` multipart through FastAPI — ALB/body limits, cost, coupling.
- Multipart through API Gateway — same proxy tax; not the Stage 1 path.

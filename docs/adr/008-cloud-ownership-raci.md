# ADR-008: Cloud ownership RACI

- **Status:** Accepted
- **Date:** 2026-04-08
- **Spec refs:** §12 ADR-008; [`docs/ownership-raci.md`](../ownership-raci.md)

## Context

Outstaff and platform design reviews ask “who owns S3 / DLQ / IAM?” Without an explicit matrix, ClickOps and unclear on-call ownership become the default.

## Decision

Publish and maintain a **RACI matrix** in [`docs/ownership-raci.md`](../ownership-raci.md). Example: S3 bucket policy/lifecycle is owned by Platform SRE via `terraform/modules/s3`; Platform Lead is Accountable; Backend is Consulted. The application **never** “fixes” bucket policy at runtime or in the console.

## Consequences

- Clear Responsible/Accountable for infra vs schema vs DLQ vs FinOps.
- Any ClickOps exception needs an ADR and RACI update.
- Operators point to the matrix and Terraform PRs, not tribal knowledge.

## Alternatives considered

- Informal “everyone owns cloud” — design-review red flag; rejected.
- App runtime mutating bucket policy — security and ownership anti-pattern.

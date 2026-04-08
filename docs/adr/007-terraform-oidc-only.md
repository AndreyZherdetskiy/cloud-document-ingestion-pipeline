# ADR-007: Terraform + OIDC as the only infra change path

- **Status:** Accepted
- **Date:** 2026-04-08
- **Spec refs:** §8.8, §10.4, §12 ADR-007

## Context

ClickOps and long-lived IAM user keys in CI create unreproducible environments and secret sprawl. Design-review and ops bar require plan/apply gates and clear ownership.

## Decision

**100% of AWS resources** live in Terraform modules. ClickOps is forbidden without an ADR exception. CI assumes GitHub Actions → AWS via **OIDC** (no long-lived access keys in git or Secrets). Agents write modules and may `fmt`/`validate`/tflint/checkov; **real AWS apply only on explicit human GO**.

## Consequences

- Reproducible plans, PR review of diffs, no keys in CI.
- Module/state hygiene is mandatory (S3 backend + DynamoDB lock per environment).
- Local demo uses LocalStack/Compose — not a substitute for Terraform modules as the AWS story.

## Alternatives considered

- Console + CloudFormation — weak review and ownership.
- Long-lived IAM users for CI — secret risk; rejected.

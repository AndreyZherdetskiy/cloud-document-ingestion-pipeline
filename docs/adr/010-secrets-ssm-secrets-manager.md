# ADR-010: Secrets via SSM and Secrets Manager

- **Status:** Accepted
- **Date:** 2026-06-15
- **Spec refs:** §5.4, §8.3, §12 ADR-010

## Context

Plaintext secrets in Terraform state, git, or ECS task definition env are a common failure mode. Local Compose needs a simple `.env` path without calling AWS APIs.

## Decision

**AWS path:** non-secret config in **SSM Parameter Store**; DB credentials (and similar) in **Secrets Manager**, injected into ECS tasks. **Local path:** gitignored `.env` + Pydantic Settings only — Compose does not call Secrets Manager. Real AWS wiring is Terraform-only and not applied unless human GO.

## Consequences

- Auditable secret access and Stage 2 rotation readiness.
- Extra IAM read permissions on task roles; cold-start latency is negligible.
- `.env.example` holds placeholders only — never real production secrets.

## Alternatives considered

- Plain env in git / committed tfvars — rejected.
- HashiCorp Vault as Stage 1 Must — unnecessary AWS-native alternative for this scope.

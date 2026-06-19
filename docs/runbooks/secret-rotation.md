# Secret rotation (Secrets Manager + local `.env`)

## When

- Scheduled DB credential rotation (quarterly or on compromise).
- After rotating `DATABASE_URL` / RDS master password in AWS.
- Local dev when copying new values from a teammate or refreshed `.env.example` placeholders.

## Scope

| Path | Secret store | Who (RACI) |
|------|--------------|------------|
| AWS ECS | Secrets Manager `{env}/doc-pipeline/db` ([ADR-010](../adr/010-secrets-ssm-secrets-manager.md)) | SRE (R), Security (A) — `docs/ownership-raci.md` |
| Local Compose | gitignored `.env` from `.env.example` | Developer |

**No secrets in git.** Never commit `.env`, `terraform.tfvars`, or real ARNs with credentials.

## AWS rotation (manual runbook — no rotation Lambda in Terraform)

Terraform provisions the secret (`terraform/modules/secrets`); **rotation is operational**, not a fake Lambda in this repo.

### Prerequisites (IAM)

Task execution role needs (already scoped in `terraform/modules/iam`):

- `secretsmanager:GetSecretValue` on the DB secret ARN
- `kms:Decrypt` on the CMK used by the secret

For **manual rotation** in the console or CLI, the operator role needs:

- `secretsmanager:PutSecretValue`, `secretsmanager:UpdateSecret`, `secretsmanager:DescribeSecret`
- `rds:ModifyDBInstance` (or use RDS integration) if the master password changes at the instance

Record changes in a Terraform PR if IAM or secret metadata must change.

### Steps

1. **Announce** maintenance window; confirm no active incident on queue backlog.
2. **Rotate** the secret in Secrets Manager:
   - Console: Secrets Manager → `{env}/doc-pipeline/db` → **Rotate secret immediately** (or staged version if using RDS-managed rotation later).
   - Ensure the new JSON/string matches what the app expects (`DATABASE_URL` key in ECS task `secrets` block).
3. **Verify** the new secret version with `GetSecretValue` (operator CLI; do not paste value into tickets).
4. **Recycle ECS tasks** so containers pick up the new version:
   - Preferred: `aws ecs update-service --cluster {env}-doc-pipeline --service {env}-processing-worker --force-new-deployment` (repeat for `{env}-api`, `{env}-ingestion-worker`).
   - Or scale desired count to 0 then back (disruptive; avoid in prod unless necessary).
5. **Smoke test**: API `/ready`, process one document end-to-end, check worker logs for DB auth errors.
6. **Rollback**: re-enable previous secret version in Secrets Manager + force new deployment again.

## Local `.env` rotation

1. Obtain new values out-of-band (never via git).
2. Update gitignored `.env` (template: `.env.example`).
3. Recreate containers: `docker compose -p doc-pipeline up -d --force-recreate api ingestion-worker processing-worker`.
4. Run `make migrate` only if the DSN points at a fresh database.

## Related

- `docs/runbooks/iam-access-denied.md` — `AccessDenied` on `secretsmanager:GetSecretValue`
- `docs/ownership-raci.md` — Secret rotation row
- `terraform/README.md` — apply gates (staging vs prod, ADR-007)

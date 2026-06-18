# IAM AccessDenied

## When

API, worker, Terraform plan/apply, or client PUT fails with `AccessDenied` / `UnauthorizedOperation`. Deploy gates may fail if the OIDC role is too narrow or too wide (ADR-007).

## Symptoms

- Worker cannot `HeadObject` / `GetObject` / `ReceiveMessage` / `DeleteMessage`.
- Presign succeeds but client PUT is denied (bucket policy / key condition mismatch).
- GitHub Actions Terraform job fails assuming the OIDC role.

## Diagnosis

1. Capture the exact API call, resource ARN, and principal from logs (no secrets).
2. Compare against Terraform IAM modules — task roles must not use `Action: "*"`.
3. For LocalStack: confirm `infra/localstack/init-aws.sh` created bucket, queues, and notifications.
4. For CI: confirm workflow uses **OIDC** (`role-to-assume`) and does **not** set long-lived `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` secrets.

## Mitigation

1. Fix least-privilege statements in Terraform modules; open a PR so `terraform-plan.yml` shows the diff.
2. Apply only via approved workflows (`workflow_dispatch` for staging/prod apply stubs) — never ClickOps.
3. Re-test the failing call path; for poison messages caused by IAM, follow `dlq-replay.md` after the fix.
4. Rotate any accidentally committed keys immediately (they must not live in git).

## Exit criteria

Denied call succeeds under the intended role; plan shows expected IAM changes only; no static keys in workflows.

## Related

- `docs/adr/007-terraform-oidc-only.md`
- `docs/ownership-raci.md`
- `docs/runbooks/presign-expired.md`

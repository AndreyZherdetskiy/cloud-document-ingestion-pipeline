# S3 Object Lock (Compliance) + lifecycle → Glacier

Stage 3 **documentation** for audit archive (spec §3.5). Validate-only Terraform comments.
No real AWS apply in this run.

## Object Lock recreate constraint (Must read)

Amazon S3 **Object Lock** is enabled at **bucket creation** (`object_lock_enabled` on create).
You generally **cannot** turn Object Lock on for an existing bucket in place.

For this repo’s `terraform/modules/s3` bucket (`aws_s3_bucket.documents`):

- Today: versioning + abort-incomplete-multipart lifecycle only.
- Adding `object_lock_enabled = true` later is a **create-time** flag and typically forces
  **bucket replacement** (destroy/recreate) on apply — **data loss risk** unless migrated.
- **Do not** silently flip the flag in the existing resource as a “Stage 3 checkbox”.
- Correct approaches when human GO exists:
  1. **New** audit-archive bucket created with Object Lock from day one + replicate/copy, or
  2. Planned migration: new bucket → dual-write/copy → cutover Settings → retire old bucket.

## Audit-archive prefix vs inbound uploads

| Prefix / use | Object Lock? | Notes |
|--------------|--------------|-------|
| `audit-archive/` (compliance export packs) | **Yes** (future dedicated bucket or prefix policy) | WORM story for regulators; Compliance mode retention |
| Tenant inbound uploads (presign PUT) | **No** by default | Normal lifecycle; worker reads bytes; not every PUT is immutable |

Do **not** confuse WORM on audit exports with locking every document upload. Inbound objects
flow through the ingestion pipeline; audit exports are written separately (append-only narrative
in Postgres + optional S3 export) under `audit-archive/` when that path is built.

## Compliance mode (narrative)

- **Compliance** retention: even root cannot shorten retention until expires (strong WORM story).
- Use for **audit export** objects (compliance packs), not necessarily every inbound upload.
- Default retention period: document product choice (e.g. 2555 days / 7 years) in tfvars when built —
  not invented as code in this Stage without human GO.

## Lifecycle → Glacier

Goal: after hot retention, transition audit-archive prefix to **GLACIER** (flexible retrieval).

Example rule intent (not applied here):

- Filter prefix: `audit-archive/`
- Transition days: e.g. 90 → `GLACIER`
- Keep abort-incomplete-multipart rule (already in module)

Current module lifecycle only aborts multipart — Glacier rule is **future** / commented in
`terraform/modules/s3/main.tf`.

## LocalStack

LocalStack may partially emulate Object Lock; **do not** treat local behavior as Compliance proof.
Evidence for Stage 3 = this runbook + TF comments + `tf-validate`.

## RACI

Bucket policy / lifecycle: Platform SRE Accountable per `docs/ownership-raci.md` (ADR-008).
App never mutates bucket Object Lock settings at runtime. Infra changes via Terraform only (ADR-007).

## Non-goals

- Enabling Object Lock on `aws_s3_bucket.documents` in this validate-only run
- Declaring Stage Done after writing this file
- Glacier Deep Archive or Glacier Instant Retrieval (this runbook standardizes on **GLACIER**)

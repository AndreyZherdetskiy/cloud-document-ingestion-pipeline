# Disaster recovery — RPO/RTO, S3 CRR, RDS Multi-AZ

Stage 3 **documentation**. Not a contractual SLA. No real AWS failover drill is required
in this environment.

## Objectives

| Plane | Goal |
|-------|------|
| Control plane (API metadata) | Survive AZ loss via Multi-AZ RDS when enabled; reconnect clients |
| Data plane (object bytes) | Survive region loss of primary bucket via S3 CRR (when configured) |
| Audit | Same DB as status writes — primary only (ADR-011); restore from snapshots / replica promote per AWS runbooks |

## RPO / RTO (design targets)

| Scope | RPO (data loss tolerance) | RTO (time to serve again) | Mechanism |
|-------|---------------------------|---------------------------|-----------|
| Single-AZ RDS failure (Multi-AZ **on**) | ~0 for committed txns (sync standby) | Minutes (DNS failover) | RDS Multi-AZ |
| Primary region S3 loss (CRR **configured**) | Seconds–minutes (async CRR) | Hours (DNS/app endpoint cutover + IAM) | S3 CRR + versioning |
| Local Compose / LocalStack | N/A | `make compose-up` | Not DR |

These numbers are **design targets for design-review narrative**, not measured contractual SLA.
Do not claim “SLA 99.9% proven” from this document.

## S3 Cross-Region Replication (CRR)

Prerequisites (AWS): versioning on source **and** destination; IAM replication role; KMS grants if SSE-KMS.

Narrative steps (human GO + real account only):

1. Create destination bucket in secondary region (Terraform env or module).
2. Enable CRR rules for prefix (e.g. tenant uploads) or whole bucket.
3. Verify with `HeadObject` / replication metrics; document lag expectations.
4. Cutover: update app Settings / SSM `S3_BUCKET` only via Terraform + redeploy (ADR-007) — never ClickOps.

**Local:** LocalStack does not prove CRR. Skip live CRR; keep this runbook + TF comments.

## RDS Multi-AZ failover

With `multi_az = true` on `aws_db_instance`:

- AWS maintains a synchronous standby in another AZ.
- Failover updates the instance DNS endpoint; clients must reconnect (SQLAlchemy pool recycle).
- **Writes and audit stay on primary endpoint** (ADR-011). Do not point write Settings at a replica.

Failover drill (real AWS only, human GO): simulate AZ impairment per AWS docs; measure reconnect; update this runbook with actual minutes.

## Local vs AWS

| Item | Local | AWS path |
|------|-------|----------|
| Postgres | single Compose service | Multi-AZ when `var.multi_az=true` |
| S3 | LocalStack bucket | Versioned bucket + optional CRR |
| Evidence this Stage | docs + `tf-validate` | same until human apply |

## Non-goals

- Active-active multi-region API
- Automatic cross-region RDS (use replica promote / PITR playbooks when needed)
- Declaring Stage Done after writing this file

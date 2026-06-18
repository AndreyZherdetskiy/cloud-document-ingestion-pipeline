# Cloud ownership RACI

Operator matrix for AWS and pipeline ownership. Source: `spec.md` §12 ADR-008. Application code never mutates bucket policies or IAM at runtime — changes go through Terraform PRs only.

**Design-review one-liner:** Platform owns S3 via the Terraform `s3` module; changes require PR + plan gate; the app never “fixes” the bucket in the console.

| Resource / process | Responsible (R) | Accountable (A) | Consulted (C) | Informed (I) |
|--------------------|-----------------|-----------------|---------------|--------------|
| S3 bucket policy / lifecycle | Platform SRE (`terraform/modules/s3`) | Platform Lead | Backend | FinOps |
| SQS + DLQ + redrive policy | Platform SRE | Platform Lead | Backend | On-call |
| ECS task definitions / services | Backend + SRE jointly | Platform Lead | QA | Product Owner |
| RDS schema / Alembic migrations | Backend | Tech Lead | SRE (capacity) | Compliance |
| IAM roles / policies | Platform SRE | Platform Lead | Security | Backend |
| CloudWatch alerts / dashboards | SRE (primary), Backend (secondary) | Platform Lead | Product Owner | On-call |
| DLQ monitoring and replay | SRE on-call | Incident Commander | Backend | Compliance |
| FinOps tags and monthly review | FinOps Analyst | FinOps Lead | SRE | Product Owner |
| Terraform state backends | Platform SRE | Platform Lead | — | Security |
| Secret rotation (Secrets Manager) | SRE | Security | Backend | Platform Lead |
| Virus/OCR/extract hook contracts | Backend | Tech Lead | DS (Stage 2) | Product Owner |
| Terraform plan/apply CI gates | Platform SRE | Platform Lead | Backend | QA |

## Notes

- FinOps tags (required): `Project=doc-pipeline`, `Environment`, `Tenant` (where applicable), `CostCenter`, `Owner`.
- ClickOps exceptions need an ADR and an update to this table.
- Local Compose/LocalStack is for development demo; production-shaped ownership is the Terraform module story above.

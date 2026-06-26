# Terraform — Cloud Document Ingestion Pipeline

Infrastructure-as-code for AWS (spec §5.4–5.5, ADR-006/007/010). **Validate only** in CI/local agents — **no `terraform apply`** without explicit human GO.

## Layout

```
terraform/
  versions.tf
  modules/
    networking/   # VPC, 3 AZ, public/private, NAT
    s3/           # documents bucket + SSE-KMS
    sqs/          # standard queue + DLQ, maxReceiveCount=5, VisibilityTimeout=300
    ecs/          # Fargate cluster, api + worker services
    rds/          # PostgreSQL
    elasticache/  # Redis
    alb/          # HTTPS-ready ALB
    iam/          # API/worker task roles + GitHub OIDC (Appendix A)
    ecr/          # api + worker repos
    cloudwatch/   # Appendix B alarms + dashboard JSON
    kms/          # CMK
    secrets/      # Secrets Manager DB + SSM config (ADR-010)
    adot/         # collector YAML: awsemf + awsxray (not Compose collector)
  environments/{dev,staging,prod}/
    *.tfvars.example
    backend.tf.example
    providers.tf.example   # default_tags FinOps
```

## Naming (spec §5.4)

| Resource | Pattern |
|----------|---------|
| S3 | `{env}-doc-pipeline-{account_id}` |
| SQS | `{env}-document-ingestion` / `-dlq` |
| ECS | `{env}-doc-pipeline` cluster; `{env}-api` / `{env}-worker` |
| RDS | `{env}-doc-pipeline-db` |
| Redis | `{env}-doc-pipeline-redis` |
| ALB | `{env}-doc-pipeline-alb` |
| Default region | `eu-central-1` |

## FinOps tags

Provider `default_tags` (and module resource tags):

- `Project=doc-pipeline`
- `Environment`
- `CostCenter`
- `Owner`

Staging footprint **estimate**: **~$200–350 / month** (see root README / spec §5.5).

## IAM (Appendix A)

- **No** `Action = "*"` on API/worker **task** roles.
- API: `s3:PutObject` (presign path); **no** `sqs:DeleteMessage`.
- Worker: `s3:GetObject` + SQS receive/delete; **no** broad `s3:PutObject` for client uploads.
- GitHub OIDC role: placeholder `EXAMPLE_ORG/doc-pipeline` subjects — no live account IDs.

## ADOT vs Compose

| Path | Collector config | Metrics | Traces |
|------|------------------|---------|--------|
| Local Compose | `infra/otel/collector.yaml` | Prometheus | Jaeger |
| AWS (this module) | `modules/adot/collector-config.yaml` | `awsemf` → CloudWatch | `awsxray` → X-Ray |

Applications always export **OTLP only**. The ADOT module ships `awsxray` in `modules/adot/collector-config.yaml` — apps never call X-Ray APIs directly.

## Apply gates (ADR-007)

| Environment | Plan | Apply |
|-------------|------|-------|
| **dev** | CI `terraform plan` on PR | Human GO for first apply; then team policy |
| **staging** | CI plan on merge to main | Auto-apply or SRE apply per team policy |
| **prod** | CI plan + required reviewers | **Manual approval** before `terraform apply` — no unattended prod apply |

Agents and CI may run `terraform fmt` / `validate` / `plan` only. Real AWS apply requires explicit human GO (see root `AGENTS.md`).

## Processing-worker autoscaling (spec §8.1)

`modules/ecs/autoscaling.tf`: target-tracking on SQS `ApproximateNumberOfMessagesVisible` (dimension `QueueName`) with backlog-per-task metric math; min/max tasks default **2–20**. Pass `processing_queue_name` from `modules/sqs` output when wiring a root stack.

## Validate (no apply)

```bash
make tf-validate
```

Downloads official HashiCorp Terraform into gitignored `.tools/terraform` if missing, then per module:

```bash
terraform init -backend=false
terraform validate
```

## Environments

Copy `backend.tf.example` → `backend.tf` and `{env}.tfvars.example` → `terraform.tfvars` (gitignored) with real account/bucket names **only on human GO**. State: S3 + DynamoDB lock placeholders.

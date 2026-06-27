locals {
  name_prefix = var.name_prefix != "" ? var.name_prefix : "${var.environment}-doc-pipeline"

  finops_tags = merge(
    {
      Project     = "doc-pipeline"
      Environment = var.environment
      CostCenter  = var.cost_center
      Owner       = var.owner
    },
    var.additional_tags,
  )
}

# ADR-010: DB credentials in Secrets Manager; non-secret config in SSM Parameter Store.

resource "aws_secretsmanager_secret" "db" {
  name       = "${var.environment}/doc-pipeline/db"
  kms_key_id = var.kms_key_arn

  tags = merge(local.finops_tags, {
    Name = "${var.environment}/doc-pipeline/db"
  })
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = var.db_secret_placeholder
}

# Rotation: operational runbook only (docs/runbooks/secret-rotation.md).
# Do not add aws_secretsmanager_secret_rotation without a real rotation Lambda ARN.
# Stage 2 delivers IAM notes + ECS task recycle steps, not a placeholder rotator.

resource "aws_ssm_parameter" "app_config" {
  for_each = {
    log_level          = "INFO"
    otlp_endpoint      = "http://localhost:4317"
    documents_bucket   = "${var.environment}-doc-pipeline-placeholder"
  }

  name  = "/doc-pipeline/${var.environment}/${each.key}"
  type  = "String"
  value = each.value

  tags = local.finops_tags
}

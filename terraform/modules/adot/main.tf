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

# ADOT collector config (awsemf + awsxray) — separate from Compose infra/otel/collector.yaml.
# Apps export OTLP only; this module owns the AWS backend wiring.

locals {
  collector_yaml = file("${path.module}/collector-config.yaml")
}

resource "aws_ssm_parameter" "adot_collector_config" {
  name  = "/doc-pipeline/${var.environment}/adot/collector-config"
  type  = "String"
  value = local.collector_yaml

  tags = merge(local.finops_tags, {
    Name = "${local.name_prefix}-adot-collector-config"
  })
}

resource "aws_cloudwatch_log_group" "adot" {
  name              = "/aws/ecs/${var.environment}/adot"
  retention_in_days = var.log_retention_days

  tags = local.finops_tags
}

data "aws_iam_policy_document" "adot_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "adot" {
  name               = "${local.name_prefix}-adot"
  assume_role_policy = data.aws_iam_policy_document.adot_assume.json

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-adot" })
}

data "aws_iam_policy_document" "adot" {
  statement {
    sid    = "EmfAndLogs"
    effect = "Allow"
    actions = [
      "logs:PutLogEvents",
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:DescribeLogGroups",
      "logs:CreateLogGroup",
    ]
    resources = [
      aws_cloudwatch_log_group.adot.arn,
      "${aws_cloudwatch_log_group.adot.arn}:*",
      "arn:aws:logs:*:*:log-group:/aws/ecs/doc-pipeline/${var.environment}/metrics*",
      "arn:aws:logs:*:*:log-group:/aws/ecs/doc-pipeline/${var.environment}/metrics*:*",
    ]
  }

  statement {
    sid    = "XRay"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    # X-Ray PutTraceSegments requires Resource="*" per AWS IAM reference.
    resources = ["*"]
  }

  statement {
    sid       = "ReadCollectorConfig"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.adot_collector_config.arn]
  }
}

resource "aws_iam_role_policy" "adot" {
  name   = "${local.name_prefix}-adot"
  role   = aws_iam_role.adot.id
  policy = data.aws_iam_policy_document.adot.json
}

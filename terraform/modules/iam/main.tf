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

# Appendix A least-privilege: no Action="*" on task roles.
# API: presign PutObject on tenant prefix; no sqs:DeleteMessage.
# Worker: GetObject + SQS receive/delete; no broad PutObject for client uploads.
# GitHub OIDC: placeholder org/repo — no live account IDs (ADR-007).

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_task" {
  name               = "${local.name_prefix}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-api-task" })
}

resource "aws_iam_role" "worker_task" {
  name               = "${local.name_prefix}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-worker-task" })
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-ecs-execution" })
}

data "aws_iam_policy_document" "api_task" {
  statement {
    sid    = "PresignPutObjectTenantPrefix"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${var.documents_bucket_arn}/*"]
  }

  statement {
    sid       = "ListBucketForPresign"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.documents_bucket_arn]
  }

  statement {
    sid    = "ReadDbSecret"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [var.db_secret_arn]
  }

  statement {
    sid    = "ReadSsmConfig"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = ["arn:aws:ssm:*:*:parameter/doc-pipeline/${var.environment}/*"]
  }

  statement {
    sid       = "KmsForS3AndSecrets"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }

  # Intentionally no sqs:DeleteMessage / ReceiveMessage on API task role (Appendix A).
}

data "aws_iam_policy_document" "worker_task" {
  statement {
    sid    = "ReadObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:HeadObject",
    ]
    resources = ["${var.documents_bucket_arn}/*"]
  }

  statement {
    sid       = "ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.documents_bucket_arn]
  }

  statement {
    sid    = "ConsumeQueue"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [var.sqs_queue_arn]
  }

  statement {
    sid    = "InspectDlq"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [var.sqs_dlq_arn]
  }

  # Stage 2 split: same worker_task role on ingestion + processing ECS services.
  # Ingestion worker enqueues PROCESS_DOCUMENT; processing worker consumes/deletes.
  statement {
    sid    = "ProcessingQueue"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [var.sqs_processing_queue_arn]
  }

  statement {
    sid    = "InspectProcessingDlq"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [var.sqs_processing_dlq_arn]
  }

  statement {
    sid    = "ReadDbSecret"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [var.db_secret_arn]
  }

  statement {
    sid    = "ReadSsmConfig"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = ["arn:aws:ssm:*:*:parameter/doc-pipeline/${var.environment}/*"]
  }

  # Producers of SSE-KMS SQS messages need GenerateDataKey + Decrypt
  # (AWS SQS key management — SendMessage to processing queue).
  statement {
    sid       = "KmsDecrypt"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }

  # No broad s3:PutObject for client uploads — clients use API-issued presigns.
}

data "aws_iam_policy_document" "ecs_execution" {
  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:log-group:/ecs/${var.environment}/*"]
  }

  statement {
    sid       = "SecretsForTaskInject"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }

  statement {
    sid       = "KmsDecryptSecrets"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "api_task" {
  name   = "${local.name_prefix}-api-task"
  role   = aws_iam_role.api_task.id
  policy = data.aws_iam_policy_document.api_task.json
}

resource "aws_iam_role_policy" "worker_task" {
  name   = "${local.name_prefix}-worker-task"
  role   = aws_iam_role.worker_task.id
  policy = data.aws_iam_policy_document.worker_task.json
}

resource "aws_iam_role_policy" "ecs_execution" {
  name   = "${local.name_prefix}-ecs-execution"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution.json
}

# GitHub Actions OIDC (placeholder — no live account IDs).
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = [var.github_oidc_audience]
  thumbprint_list = ["ffffffffffffffffffffffffffffffffffffffff"]

  tags = local.finops_tags
}

data "aws_iam_policy_document" "github_oidc_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = [var.github_oidc_audience]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = var.github_oidc_subjects
    }
  }
}

resource "aws_iam_role" "github_oidc" {
  name               = "${local.name_prefix}-github-oidc"
  assume_role_policy = data.aws_iam_policy_document.github_oidc_assume.json

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-github-oidc" })
}

data "aws_iam_policy_document" "github_oidc" {
  statement {
    sid    = "TerraformPlanScoped"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "ecs:Describe*",
      "ecs:List*",
      "s3:ListBucket",
      "s3:GetBucket*",
      "s3:GetObject",
      "sqs:GetQueueAttributes",
      "sqs:ListQueues",
      "rds:Describe*",
      "elasticache:Describe*",
      "elasticache:List*",
      "elasticloadbalancing:Describe*",
      "ecr:Describe*",
      "ecr:GetAuthorizationToken",
      "ecr:ListImages",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "logs:Describe*",
      "cloudwatch:Describe*",
      "cloudwatch:GetDashboard",
      "kms:DescribeKey",
      "kms:ListAliases",
      "secretsmanager:DescribeSecret",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:DescribeParameters",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_oidc" {
  name   = "${local.name_prefix}-github-oidc-plan"
  role   = aws_iam_role.github_oidc.id
  policy = data.aws_iam_policy_document.github_oidc.json
}

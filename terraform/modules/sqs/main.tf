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

# HashiCorp aws_sqs_queue: visibility_timeout_seconds 0–43200; redrive_policy JSON with
# deadLetterTargetArn + maxReceiveCount as integer (not string).
# https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue

resource "aws_sqs_queue" "dlq" {
  name              = "${var.environment}-document-ingestion-dlq"
  kms_master_key_id = var.kms_key_id

  message_retention_seconds = 1209600

  tags = merge(local.finops_tags, {
    Name = "${var.environment}-document-ingestion-dlq"
  })
}

resource "aws_sqs_queue" "main" {
  name                       = "${var.environment}-document-ingestion"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  kms_master_key_id          = var.kms_key_id
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.finops_tags, {
    Name = "${var.environment}-document-ingestion"
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main.arn]
  })
}

# Ingest queue only — processing queue does not receive S3 ObjectCreated events.
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-config-sqs.html
data "aws_iam_policy_document" "ingest_s3_notification" {
  statement {
    sid    = "AllowS3SendMessage"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.main.arn]

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [var.s3_bucket_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "ingest_s3_notification" {
  queue_url = aws_sqs_queue.main.id
  policy    = data.aws_iam_policy_document.ingest_s3_notification.json
}

resource "aws_sqs_queue" "processing_dlq" {
  name              = "${var.environment}-document-processing-dlq"
  kms_master_key_id = var.kms_key_id

  message_retention_seconds = 1209600

  tags = merge(local.finops_tags, {
    Name = "${var.environment}-document-processing-dlq"
  })
}

resource "aws_sqs_queue" "processing" {
  name                       = "${var.environment}-document-processing"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  kms_master_key_id          = var.kms_key_id
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.finops_tags, {
    Name = "${var.environment}-document-processing"
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "processing_dlq" {
  queue_url = aws_sqs_queue.processing_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.processing.arn]
  })
}

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

locals {
  bucket_name = "${var.environment}-doc-pipeline-${var.account_id}"
}

# S3→SQS object-created notification: aws_s3_bucket_notification below.
# LocalStack compose path mirrors this module in infra/localstack/init-aws.sh.
resource "aws_s3_bucket" "documents" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy

  tags = merge(local.finops_tags, {
    Name = local.bucket_name
  })
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Standard queue only — FIFO is not supported as an S3 notification destination.
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/ways-to-add-notification-config-to-bucket.html
resource "aws_s3_bucket_notification" "documents_object_created" {
  bucket = aws_s3_bucket.documents.id

  queue {
    queue_arn = var.ingest_queue_arn
    events    = ["s3:ObjectCreated:*"]
  }
}

# Stage 3 DR (docs/runbooks/dr-rpo-rto.md) — NOT applied until destination module/vars exist:
# - Cross-Region Replication requires a destination bucket + iam role in another region.
# - Do not add aws_s3_bucket_replication_configuration until destination module/vars exist
#   and human GO for real AWS. Versioning is already Enabled above (CRR prerequisite).

# ---------------------------------------------------------------------------
# Stage 3 Object Lock / Glacier (docs/runbooks/s3-object-lock-glacier.md)
# DO NOT set object_lock_enabled on aws_s3_bucket.documents above without a
# deliberate create-new-bucket migration — enable-at-create only; in-place toggle
# risks forced replace.
#
# Future (new bucket or greenfield) sketch — commented intentionally:
# resource "aws_s3_bucket" "audit_archive" {
#   bucket              = "${var.environment}-doc-pipeline-audit-${var.account_id}"
#   object_lock_enabled = true
# }
# resource "aws_s3_bucket_object_lock_configuration" "audit_archive" {
#   bucket = aws_s3_bucket.audit_archive.id
#   rule {
#     default_retention {
#       mode = "COMPLIANCE"
#       days = 2555  # example 7y — set in tfvars when human GO
#     }
#   }
# }
# resource "aws_s3_bucket_lifecycle_configuration" "audit_archive" {
#   bucket = aws_s3_bucket.audit_archive.id
#   rule {
#     id     = "audit-archive-to-glacier"
#     status = "Enabled"
#     filter { prefix = "audit-archive/" }
#     transition {
#       days          = 90
#       storage_class = "GLACIER"
#     }
#   }
# }
# ---------------------------------------------------------------------------

variable "environment" {
  description = "Environment name (dev|staging|prod)."
  type        = string
}

variable "cost_center" {
  description = "FinOps cost center tag."
  type        = string
}

variable "owner" {
  description = "FinOps owner / RACI team tag."
  type        = string
}

variable "name_prefix" {
  description = "Optional override; default {env}-doc-pipeline naming from spec §5.4."
  type        = string
  default     = ""
}

variable "additional_tags" {
  description = "Extra tags merged with FinOps defaults."
  type        = map(string)
  default     = {}
}

variable "kms_key_id" {
  description = "KMS key id/ARN for SQS SSE."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "Queue visibility timeout (spec §5.4: 300)."
  type        = number
  default     = 300
}

variable "max_receive_count" {
  description = "Redrive maxReceiveCount before DLQ (spec: 5)."
  type        = number
  default     = 5
}

variable "s3_bucket_arn" {
  description = "Documents bucket ARN for S3→SQS ingest queue policy (aws:SourceArn). Pass modules/s3 output bucket_arn when wiring a root stack."
  type        = string
}

variable "aws_account_id" {
  description = "AWS account id for S3→SQS queue policy condition aws:SourceAccount. Must match the bucket owner account."
  type        = string
}

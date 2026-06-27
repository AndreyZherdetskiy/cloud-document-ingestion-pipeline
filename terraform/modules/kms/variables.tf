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

variable "aws_account_id" {
  description = "AWS account id for CMK root principal (EnableIamUserPermissions)."
  type        = string
}

variable "documents_bucket_arn" {
  description = "Documents bucket ARN for S3→SSE-KMS SQS ingest (kms key policy aws:SourceArn). Pass modules/s3 output bucket_arn when wiring a root stack."
  type        = string
}

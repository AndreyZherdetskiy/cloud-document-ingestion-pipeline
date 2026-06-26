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

variable "documents_bucket_arn" {
  description = "S3 documents bucket ARN."
  type        = string
}

variable "sqs_queue_arn" {
  description = "Main ingestion queue ARN."
  type        = string
}

variable "sqs_dlq_arn" {
  description = "DLQ ARN (admin/replay paths)."
  type        = string
}

variable "sqs_processing_queue_arn" {
  description = "Processing queue ARN (ingestion worker enqueue + processing worker consume)."
  type        = string
}

variable "sqs_processing_dlq_arn" {
  description = "Processing DLQ ARN (admin/replay paths)."
  type        = string
}

variable "db_secret_arn" {
  description = "Secrets Manager DB secret ARN."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK ARN for decrypt/encrypt where needed."
  type        = string
}

variable "github_oidc_subjects" {
  description = "GitHub OIDC sub claim patterns (placeholder repo)."
  type        = list(string)
  default = [
    "repo:EXAMPLE_ORG/doc-pipeline:ref:refs/heads/main",
    "repo:EXAMPLE_ORG/doc-pipeline:environment:staging",
  ]
}

variable "github_oidc_audience" {
  description = "OIDC audience (sts.amazonaws.com)."
  type        = string
  default     = "sts.amazonaws.com"
}

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

variable "account_id" {
  description = "AWS account id placeholder for bucket naming (spec §5.4). Use 000000000000 until wired."
  type        = string
  default     = "000000000000"
}

variable "kms_key_arn" {
  description = "KMS CMK ARN for SSE-KMS."
  type        = string
}

variable "ingest_queue_arn" {
  description = "Ingest (document-ingestion) Standard queue ARN for s3:ObjectCreated:* notifications. Pass modules/sqs output queue_arn — not the processing queue."
  type        = string
}

variable "force_destroy" {
  description = "Allow destroy with objects (dev only)."
  type        = bool
  default     = false
}

# Future: enable_object_lock (default false) — Object Lock is create-time only on a NEW bucket.
# Do not wire this to aws_s3_bucket.documents without a migration plan; see
# docs/runbooks/s3-object-lock-glacier.md.

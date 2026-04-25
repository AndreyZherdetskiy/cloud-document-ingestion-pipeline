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

variable "kms_key_arn" {
  description = "KMS key for Secrets Manager / SSM SecureString."
  type        = string
}

variable "db_secret_placeholder" {
  description = "Placeholder secret string (never real creds in git)."
  type        = string
  default     = "{\"username\":\"doc_pipeline\",\"password\":\"CHANGE_ME\"}"
  sensitive   = true
}

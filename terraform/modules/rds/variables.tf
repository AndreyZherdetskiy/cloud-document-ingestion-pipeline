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

variable "subnet_ids" {
  type = list(string)
}

variable "vpc_security_group_ids" {
  type = list(string)
}

variable "kms_key_arn" {
  type = string
}

variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "allocated_storage" {
  type    = number
  default = 50
}

variable "db_name" {
  type    = string
  default = "doc_pipeline"
}

variable "master_username" {
  type    = string
  default = "doc_pipeline"
}

variable "master_password" {
  description = "Placeholder only — wire Secrets Manager in env root; never commit real password."
  type        = string
  sensitive   = true
  default     = "CHANGE_ME_PLACEHOLDER_ONLY"
}

variable "enable_read_replica" {
  description = "When true, create a same-region read replica (ADR-011). Default false for validate-only green."
  type        = bool
  default     = false
}

variable "replica_instance_class" {
  description = "Instance class for optional read replica."
  type        = string
  default     = "db.t4g.medium"
}

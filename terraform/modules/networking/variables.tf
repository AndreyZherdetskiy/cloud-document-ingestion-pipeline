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

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of AZs (spec: 3)."
  type        = number
  default     = 3
}

variable "single_nat_gateway" {
  description = "Use one NAT (dev/staging cost); prod typically false."
  type        = bool
  default     = true
}

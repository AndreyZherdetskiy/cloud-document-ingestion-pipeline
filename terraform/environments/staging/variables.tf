variable "aws_region" {
  description = "AWS region (spec default eu-central-1)."
  type        = string
  default     = "eu-central-1"
}

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

variable "account_id" {
  description = "AWS account id for bucket naming and IAM conditions (placeholder until human GO)."
  type        = string
  default     = "000000000000"
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway (dev/staging cost); prod typically false."
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Allow S3 destroy with objects (dev only)."
  type        = bool
  default     = false
}

variable "enable_https" {
  description = "Attach HTTPS listener when certificate_arn is set."
  type        = bool
  default     = false
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS (empty until DNS wired)."
  type        = string
  default     = ""
}

variable "enable_read_replica" {
  description = "Create RDS read replica (ADR-011); default false for validate-only."
  type        = bool
  default     = false
}

variable "multi_az" {
  description = "RDS multi-AZ (staging/prod DR); default false for dev validate."
  type        = bool
  default     = false
}

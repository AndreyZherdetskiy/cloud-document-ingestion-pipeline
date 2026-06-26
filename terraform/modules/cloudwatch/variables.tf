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

variable "sqs_queue_name" {
  description = "Main queue name for metrics."
  type        = string
}

variable "sqs_dlq_name" {
  description = "DLQ name for metrics."
  type        = string
}

variable "alb_arn_suffix" {
  description = "ALB ARN suffix for 5xx metrics (aws_lb.arn_suffix)."
  type        = string
}

variable "rds_instance_id" {
  description = "RDS DBInstanceIdentifier."
  type        = string
}

variable "ecs_cluster_name" {
  type = string
}

variable "ecs_worker_service_name" {
  type = string
}

variable "alarm_actions" {
  description = "SNS topic ARNs (placeholder empty until wired)."
  type        = list(string)
  default     = []
}

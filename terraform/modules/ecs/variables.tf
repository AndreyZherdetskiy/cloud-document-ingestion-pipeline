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

variable "private_subnet_ids" {
  description = "Private subnet IDs for Fargate tasks."
  type        = list(string)
}

variable "api_security_group_id" {
  description = "Security group for API tasks."
  type        = string
}

variable "worker_security_group_id" {
  description = "Security group for worker tasks."
  type        = string
}

variable "api_image" {
  description = "ECR image URI for API."
  type        = string
}

variable "worker_image" {
  description = "ECR image URI for worker."
  type        = string
}

variable "api_execution_role_arn" {
  type = string
}

variable "api_task_role_arn" {
  type = string
}

variable "worker_execution_role_arn" {
  type = string
}

variable "worker_task_role_arn" {
  type = string
}

variable "target_group_arn" {
  description = "ALB target group for API service."
  type        = string
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 2
}

variable "ingestion_worker_desired_count" {
  type    = number
  default = 2
}

variable "processing_worker_desired_count" {
  type    = number
  default = 2
}

variable "processing_worker_min_count" {
  description = "Minimum processing-worker tasks (spec §8.1 autoscaling floor)."
  type        = number
  default     = 2
}

variable "processing_worker_max_count" {
  description = "Maximum processing-worker tasks (spec §8.1 autoscaling ceiling)."
  type        = number
  default     = 20
}

variable "processing_queue_name" {
  description = "SQS processing queue name for autoscaling QueueName dimension; default {env}-document-processing."
  type        = string
  default     = ""
}

variable "processing_worker_target_backlog_per_task" {
  description = "Target SQS backlog per running processing-worker task for target-tracking policy."
  type        = number
  default     = 10
}

variable "processing_worker_scale_in_cooldown" {
  description = "Seconds before scale-in after a scale-out event."
  type        = number
  default     = 300
}

variable "processing_worker_scale_out_cooldown" {
  description = "Seconds before another scale-out after the previous one."
  type        = number
  default     = 60
}

variable "db_secret_arn" {
  type = string
}

output "cluster_id" {
  value = aws_ecs_cluster.this.id
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "api_service_name" {
  value = aws_ecs_service.api.name
}

output "ingestion_worker_service_name" {
  value = aws_ecs_service.ingestion_worker.name
}

output "processing_worker_service_name" {
  value = aws_ecs_service.processing_worker.name
}

# Compat alias for Stage 1 cloudwatch wiring (ingestion as primary worker name).
output "worker_service_name" {
  value = aws_ecs_service.ingestion_worker.name
}

output "api_log_group_name" {
  value = aws_cloudwatch_log_group.api.name
}

output "ingestion_worker_log_group_name" {
  value = aws_cloudwatch_log_group.ingestion_worker.name
}

output "processing_worker_log_group_name" {
  value = aws_cloudwatch_log_group.processing_worker.name
}

output "worker_log_group_name" {
  value = aws_cloudwatch_log_group.ingestion_worker.name
}

output "processing_worker_autoscaling_target_resource_id" {
  value = aws_appautoscaling_target.processing_worker.resource_id
}

output "processing_worker_autoscaling_policy_arn" {
  value = aws_appautoscaling_policy.processing_worker.arn
}

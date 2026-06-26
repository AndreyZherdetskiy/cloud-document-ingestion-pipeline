output "collector_config_parameter_arn" {
  value = aws_ssm_parameter.adot_collector_config.arn
}

output "collector_config_parameter_name" {
  value = aws_ssm_parameter.adot_collector_config.name
}

output "adot_task_role_arn" {
  value = aws_iam_role.adot.arn
}

output "adot_log_group_name" {
  value = aws_cloudwatch_log_group.adot.name
}

output "exporters" {
  description = "ADOT exporters used on AWS path (apps stay OTLP-only)."
  value       = ["awsemf", "awsxray"]
}

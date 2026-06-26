output "alarm_names" {
  description = "Appendix B primary alarm names."
  value = [
    aws_cloudwatch_metric_alarm.dlq_visible.alarm_name,
    aws_cloudwatch_metric_alarm.queue_oldest_message_age.alarm_name,
    aws_cloudwatch_metric_alarm.api_5xx_rate.alarm_name,
    aws_cloudwatch_metric_alarm.rds_cpu.alarm_name,
    aws_cloudwatch_composite_alarm.worker_zero_with_depth.alarm_name,
  ]
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.pipeline.dashboard_name
}

output "dashboard_body" {
  description = "CloudWatch dashboard JSON (Appendix B)."
  value       = local.dashboard_body
}

output "db_secret_arn" {
  value = aws_secretsmanager_secret.db.arn
}

output "db_secret_name" {
  value = aws_secretsmanager_secret.db.name
}

output "ssm_parameter_arns" {
  value = [for p in aws_ssm_parameter.app_config : p.arn]
}

output "db_instance_id" {
  value = aws_db_instance.this.id
}

output "db_instance_arn" {
  value = aws_db_instance.this.arn
}

output "db_endpoint" {
  value = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "replica_address" {
  description = "Read replica address when enable_read_replica=true; else null."
  value       = try(aws_db_instance.replica[0].address, null)
}

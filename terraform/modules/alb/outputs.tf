output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "alb_arn_suffix" {
  description = "ALB ARN suffix for CloudWatch ApplicationELB metrics."
  value       = aws_lb.this.arn_suffix
}

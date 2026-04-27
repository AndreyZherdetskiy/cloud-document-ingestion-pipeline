output "queue_url" {
  value = aws_sqs_queue.main.url
}

output "queue_arn" {
  value = aws_sqs_queue.main.arn
}

output "queue_name" {
  value = aws_sqs_queue.main.name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "dlq_name" {
  value = aws_sqs_queue.dlq.name
}

output "processing_queue_url" {
  value = aws_sqs_queue.processing.url
}

output "processing_queue_arn" {
  value = aws_sqs_queue.processing.arn
}

output "processing_queue_name" {
  value = aws_sqs_queue.processing.name
}

output "processing_dlq_url" {
  value = aws_sqs_queue.processing_dlq.url
}

output "processing_dlq_arn" {
  value = aws_sqs_queue.processing_dlq.arn
}

output "processing_dlq_name" {
  value = aws_sqs_queue.processing_dlq.name
}

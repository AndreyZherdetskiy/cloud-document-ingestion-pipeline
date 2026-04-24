# spec §8.1: processing-worker autoscaling 2–20 tasks on SQS queue depth.
# Target tracking with metric math (backlog per task) per:
# https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-target-tracking-metric-math.html
# ECS Fargate scalable target:
# https://repost.aws/knowledge-center/ecs-fargate-service-auto-scaling

locals {
  processing_queue_name = var.processing_queue_name != "" ? var.processing_queue_name : "${var.environment}-document-processing"
}

resource "aws_appautoscaling_target" "processing_worker" {
  max_capacity       = var.processing_worker_max_count
  min_capacity       = var.processing_worker_min_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.processing_worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "processing_worker" {
  name               = "${var.environment}-processing-worker-sqs-depth"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.processing_worker.resource_id
  scalable_dimension = aws_appautoscaling_target.processing_worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.processing_worker.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.processing_worker_target_backlog_per_task
    scale_in_cooldown  = var.processing_worker_scale_in_cooldown
    scale_out_cooldown = var.processing_worker_scale_out_cooldown

    customized_metric_specification {
      metrics {
        id = "m1"

        metric_stat {
          metric {
            metric_name = "ApproximateNumberOfMessagesVisible"
            namespace   = "AWS/SQS"

            dimensions {
              name  = "QueueName"
              value = local.processing_queue_name
            }
          }

          stat = "Average"
        }
      }

      metrics {
        id          = "e1"
        expression  = "m1 / RUNNING_TASK_COUNT"
        label       = "ApproximateNumberOfMessagesVisible per running task"
        return_data = true
      }
    }
  }
}

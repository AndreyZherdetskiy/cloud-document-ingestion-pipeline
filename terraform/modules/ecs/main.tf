locals {
  name_prefix = var.name_prefix != "" ? var.name_prefix : "${var.environment}-doc-pipeline"

  finops_tags = merge(
    {
      Project     = "doc-pipeline"
      Environment = var.environment
      CostCenter  = var.cost_center
      Owner       = var.owner
    },
    var.additional_tags,
  )
}

# ADR-006: ECS Fargate for API + ingestion/processing workers (not Lambda-only / EKS).

resource "aws_ecs_cluster" "this" {
  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(local.finops_tags, { Name = local.name_prefix })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.environment}/api"
  retention_in_days = var.log_retention_days

  tags = local.finops_tags
}

resource "aws_cloudwatch_log_group" "ingestion_worker" {
  name              = "/ecs/${var.environment}/ingestion-worker"
  retention_in_days = var.log_retention_days

  tags = local.finops_tags
}

resource "aws_cloudwatch_log_group" "processing_worker" {
  name              = "/ecs/${var.environment}/processing-worker"
  retention_in_days = var.log_retention_days

  tags = local.finops_tags
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = var.api_execution_role_arn
  task_role_arn            = var.api_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image
      essential = true
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      secrets = [{
        name      = "DATABASE_URL"
        valueFrom = var.db_secret_arn
      }]
      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = "eu-central-1"
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])

  tags = local.finops_tags
}

resource "aws_ecs_task_definition" "ingestion_worker" {
  family                   = "${var.environment}-ingestion-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = var.worker_execution_role_arn
  task_role_arn            = var.worker_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "ingestion-worker"
      image     = var.worker_image
      essential = true
      command   = ["python", "-m", "doc_pipeline.worker.ingestion_main"]
      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
        { name = "OTEL_SERVICE_NAME", value = "doc-pipeline-ingestion-worker" },
      ]
      secrets = [{
        name      = "DATABASE_URL"
        valueFrom = var.db_secret_arn
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ingestion_worker.name
          "awslogs-region"        = "eu-central-1"
          "awslogs-stream-prefix" = "ingestion-worker"
        }
      }
    }
  ])

  tags = local.finops_tags
}

resource "aws_ecs_task_definition" "processing_worker" {
  family                   = "${var.environment}-processing-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = var.worker_execution_role_arn
  task_role_arn            = var.worker_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "processing-worker"
      image     = var.worker_image
      essential = true
      command   = ["python", "-m", "doc_pipeline.worker.processing_main"]
      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
        { name = "OTEL_SERVICE_NAME", value = "doc-pipeline-processing-worker" },
      ]
      secrets = [{
        name      = "DATABASE_URL"
        valueFrom = var.db_secret_arn
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.processing_worker.name
          "awslogs-region"        = "eu-central-1"
          "awslogs-stream-prefix" = "processing-worker"
        }
      }
    }
  ])

  tags = local.finops_tags
}

resource "aws_ecs_service" "api" {
  name            = "${var.environment}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.api_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "api"
    container_port   = 8000
  }

  tags = local.finops_tags
}

resource "aws_ecs_service" "ingestion_worker" {
  name            = "${var.environment}-ingestion-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ingestion_worker.arn
  desired_count   = var.ingestion_worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.worker_security_group_id]
    assign_public_ip = false
  }

  tags = local.finops_tags
}

resource "aws_ecs_service" "processing_worker" {
  name            = "${var.environment}-processing-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.processing_worker.arn
  desired_count   = var.processing_worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.worker_security_group_id]
    assign_public_ip = false
  }

  # App Auto Scaling owns steady-state count (min/max). Terraform would otherwise
  # reset desired_count on every apply. HashiCorp aws_ecs_service + Application Auto Scaling.
  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = local.finops_tags
}

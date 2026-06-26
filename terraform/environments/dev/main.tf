locals {
  name_prefix           = "${var.environment}-doc-pipeline"
  documents_bucket_name = "${var.environment}-doc-pipeline-${var.account_id}"
  # Predicted ARN — matches modules/s3 local.bucket_name before apply (breaks KMS↔SQS↔S3 cycles).
  documents_bucket_arn = "arn:aws:s3:::${local.documents_bucket_name}"

  finops = {
    environment = var.environment
    cost_center = var.cost_center
    owner       = var.owner
  }
}

module "networking" {
  source = "../../modules/networking"

  environment        = local.finops.environment
  cost_center        = local.finops.cost_center
  owner              = local.finops.owner
  single_nat_gateway = var.single_nat_gateway
}

module "ecr" {
  source = "../../modules/ecr"

  environment = local.finops.environment
  cost_center = local.finops.cost_center
  owner       = local.finops.owner
}

module "kms" {
  source = "../../modules/kms"

  environment          = local.finops.environment
  cost_center          = local.finops.cost_center
  owner                = local.finops.owner
  aws_account_id       = var.account_id
  documents_bucket_arn = local.documents_bucket_arn
}

module "sqs" {
  source = "../../modules/sqs"

  environment     = local.finops.environment
  cost_center     = local.finops.cost_center
  owner           = local.finops.owner
  kms_key_id      = module.kms.key_arn
  s3_bucket_arn   = local.documents_bucket_arn
  aws_account_id  = var.account_id
}

module "s3" {
  source = "../../modules/s3"

  environment      = local.finops.environment
  cost_center      = local.finops.cost_center
  owner            = local.finops.owner
  account_id       = var.account_id
  kms_key_arn      = module.kms.key_arn
  ingest_queue_arn = module.sqs.queue_arn
  force_destroy    = var.force_destroy
}

module "secrets" {
  source = "../../modules/secrets"

  environment = local.finops.environment
  cost_center = local.finops.cost_center
  owner       = local.finops.owner
  kms_key_arn = module.kms.key_arn
}

module "alb" {
  source = "../../modules/alb"

  environment         = local.finops.environment
  cost_center         = local.finops.cost_center
  owner               = local.finops.owner
  vpc_id              = module.networking.vpc_id
  public_subnet_ids   = module.networking.public_subnet_ids
  enable_https        = var.enable_https
  certificate_arn     = var.certificate_arn
}

# ECS/RDS/ElastiCache SGs in root — ALB SG stays in modules/alb.
resource "aws_security_group" "api" {
  name        = "${local.name_prefix}-api"
  description = "API ECS tasks — ingress from ALB only"
  vpc_id      = module.networking.vpc_id

  ingress {
    description     = "HTTP from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [module.alb.alb_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name_prefix}-api"
    Project     = "doc-pipeline"
    Environment = var.environment
    CostCenter  = var.cost_center
    Owner       = var.owner
  }
}

resource "aws_security_group" "worker" {
  name        = "${local.name_prefix}-worker"
  description = "Worker ECS tasks — no public ingress"
  vpc_id      = module.networking.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name_prefix}-worker"
    Project     = "doc-pipeline"
    Environment = var.environment
    CostCenter  = var.cost_center
    Owner       = var.owner
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds"
  description = "PostgreSQL from API and worker tasks"
  vpc_id      = module.networking.vpc_id

  ingress {
    description     = "PostgreSQL from API"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  ingress {
    description     = "PostgreSQL from workers"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name_prefix}-rds"
    Project     = "doc-pipeline"
    Environment = var.environment
    CostCenter  = var.cost_center
    Owner       = var.owner
  }
}

resource "aws_security_group" "redis" {
  name        = "${local.name_prefix}-redis"
  description = "Redis from API and worker tasks"
  vpc_id      = module.networking.vpc_id

  ingress {
    description     = "Redis from API"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  ingress {
    description     = "Redis from workers"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name_prefix}-redis"
    Project     = "doc-pipeline"
    Environment = var.environment
    CostCenter  = var.cost_center
    Owner       = var.owner
  }
}

module "rds" {
  source = "../../modules/rds"

  environment            = local.finops.environment
  cost_center            = local.finops.cost_center
  owner                  = local.finops.owner
  subnet_ids             = module.networking.private_subnet_ids
  vpc_security_group_ids = [aws_security_group.rds.id]
  kms_key_arn            = module.kms.key_arn
  multi_az               = var.multi_az
  enable_read_replica    = var.enable_read_replica
}

module "elasticache" {
  source = "../../modules/elasticache"

  environment        = local.finops.environment
  cost_center        = local.finops.cost_center
  owner              = local.finops.owner
  subnet_ids         = module.networking.private_subnet_ids
  security_group_ids = [aws_security_group.redis.id]
}

module "iam" {
  source = "../../modules/iam"

  environment                = local.finops.environment
  cost_center                = local.finops.cost_center
  owner                      = local.finops.owner
  documents_bucket_arn       = module.s3.bucket_arn
  sqs_queue_arn              = module.sqs.queue_arn
  sqs_dlq_arn                = module.sqs.dlq_arn
  sqs_processing_queue_arn   = module.sqs.processing_queue_arn
  sqs_processing_dlq_arn     = module.sqs.processing_dlq_arn
  db_secret_arn              = module.secrets.db_secret_arn
  kms_key_arn                = module.kms.key_arn
}

module "ecs" {
  source = "../../modules/ecs"

  environment                     = local.finops.environment
  cost_center                     = local.finops.cost_center
  owner                           = local.finops.owner
  private_subnet_ids              = module.networking.private_subnet_ids
  api_security_group_id           = aws_security_group.api.id
  worker_security_group_id        = aws_security_group.worker.id
  api_image                       = "${module.ecr.api_repository_url}:latest"
  worker_image                    = "${module.ecr.worker_repository_url}:latest"
  api_execution_role_arn          = module.iam.ecs_execution_role_arn
  api_task_role_arn               = module.iam.api_task_role_arn
  worker_execution_role_arn       = module.iam.ecs_execution_role_arn
  worker_task_role_arn            = module.iam.worker_task_role_arn
  target_group_arn                = module.alb.target_group_arn
  db_secret_arn                   = module.secrets.db_secret_arn
  processing_queue_name           = module.sqs.processing_queue_name
}

module "adot" {
  source = "../../modules/adot"

  environment = local.finops.environment
  cost_center = local.finops.cost_center
  owner       = local.finops.owner
}

module "cloudwatch" {
  source = "../../modules/cloudwatch"

  environment             = local.finops.environment
  cost_center             = local.finops.cost_center
  owner                   = local.finops.owner
  sqs_queue_name          = module.sqs.queue_name
  sqs_dlq_name            = module.sqs.dlq_name
  alb_arn_suffix          = module.alb.alb_arn_suffix
  rds_instance_id         = module.rds.db_instance_id
  ecs_cluster_name        = module.ecs.cluster_name
  ecs_worker_service_name = module.ecs.worker_service_name
}

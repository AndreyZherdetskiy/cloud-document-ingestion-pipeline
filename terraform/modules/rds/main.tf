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

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-db"
  subnet_ids = var.subnet_ids

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-db" })
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name_prefix}-db"
  engine         = "postgres"
  engine_version = "16"

  instance_class        = var.instance_class
  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.allocated_storage * 2
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_name  = var.db_name
  username = var.master_username
  password = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.vpc_security_group_ids
  # Stage 3 DR: set multi_az=true in staging/prod tfvars for AZ failover (see docs/runbooks/dr-rpo-rto.md).
  # Failover is DNS-based; apps must reconnect. Writes/audit always use this primary endpoint (ADR-011).
  # App DB grants must omit DELETE/UPDATE on audit_log (ADR-003); Alembic also installs a BEFORE
  # UPDATE OR DELETE trigger so even the table owner cannot mutate rows.
  multi_az               = var.multi_az
  publicly_accessible    = false

  backup_retention_period = 7
  skip_final_snapshot     = true
  deletion_protection     = false

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-db" })
}

# ADR-011 / Stage 3: optional read replica for list/audit reads. Writes stay on primary above.
resource "aws_db_instance" "replica" {
  count = var.enable_read_replica ? 1 : 0

  identifier          = "${local.name_prefix}-db-replica"
  replicate_source_db = aws_db_instance.this.identifier
  instance_class      = var.replica_instance_class
  publicly_accessible = false
  skip_final_snapshot = true

  tags = merge(local.finops_tags, { Name = "${local.name_prefix}-db-replica", Role = "read-replica" })
}

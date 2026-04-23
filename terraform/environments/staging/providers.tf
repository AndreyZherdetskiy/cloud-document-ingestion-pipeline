# Live provider for validate/plan. Copy backend.tf.example → backend.tf on human GO for remote state.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "doc-pipeline"
      Environment = var.environment
      CostCenter  = var.cost_center
      Owner       = var.owner
    }
  }
}

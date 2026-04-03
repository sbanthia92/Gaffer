terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment and configure once the S3 state bucket exists:
  # backend "s3" {
  #   bucket = "gaffer-terraform-state"
  #   key    = "gaffer/terraform.tfstate"
  #   region = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region
}

# ── ECR ────────────────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "gaffer_api" {
  name                 = "gaffer-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Environment = var.environment
    Project     = "the-gaffer"
  }
}

resource "aws_ecr_lifecycle_policy" "gaffer_api" {
  repository = aws_ecr_repository.gaffer_api.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ── EKS ────────────────────────────────────────────────────────────────────────
# Placeholder — uncomment and configure the EKS module to provision the cluster.
#
# module "eks" {
#   source          = "terraform-aws-modules/eks/aws"
#   version         = "~> 20.0"
#
#   cluster_name    = var.eks_cluster_name
#   cluster_version = "1.30"
#
#   eks_managed_node_groups = {
#     default = {
#       instance_types = [var.eks_node_instance_type]
#       desired_size   = var.eks_desired_nodes
#       min_size       = 1
#       max_size       = 5
#     }
#   }
#
#   tags = {
#     Environment = var.environment
#     Project     = "the-gaffer"
#   }
# }

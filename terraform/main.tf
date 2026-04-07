terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment once the S3 state bucket exists:
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
# Kept for future use (Stage 3/4 ECS/EKS migration).

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

# ── IAM role for EC2 (SES send access) ────────────────────────────────────────

resource "aws_iam_role" "gaffer_ec2" {
  name = "gaffer-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Project = "the-gaffer"
  }
}

resource "aws_iam_role_policy" "gaffer_secrets" {
  name = "gaffer-secrets-read"
  role = aws_iam_role.gaffer_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:gaffer/production*"
    }]
  })
}

resource "aws_iam_role_policy" "gaffer_cloudwatch" {
  name = "gaffer-cloudwatch-logs"
  role = aws_iam_role.gaffer_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
      ]
      Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/gaffer/*"
    }]
  })
}

resource "aws_cloudwatch_log_group" "gaffer_api" {
  name              = "/gaffer/production/api"
  retention_in_days = 30

  tags = {
    Project     = "the-gaffer"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "gaffer_ssm" {
  role       = aws_iam_role.gaffer_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "gaffer_ec2" {
  name = "gaffer-ec2-profile"
  role = aws_iam_role.gaffer_ec2.name
}

# ── Security group ─────────────────────────────────────────────────────────────

resource "aws_security_group" "gaffer" {
  name        = "gaffer-ec2"
  description = "Allow SSH, HTTP, and HTTPS inbound; all outbound"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = var.environment
    Project     = "the-gaffer"
  }
}

# ── EC2 instance ───────────────────────────────────────────────────────────────

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "gaffer" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.ec2_instance_type
  key_name               = var.ec2_key_name
  vpc_security_group_ids = [aws_security_group.gaffer.id]
  iam_instance_profile   = aws_iam_instance_profile.gaffer_ec2.name
  user_data              = file("${path.module}/../scripts/bootstrap_ec2.sh")

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  tags = {
    Name        = "gaffer"
    Environment = var.environment
    Project     = "the-gaffer"
  }
}

# ── Elastic IP ─────────────────────────────────────────────────────────────────

resource "aws_eip" "gaffer" {
  instance = aws_instance.gaffer.id
  domain   = "vpc"

  tags = {
    Name        = "gaffer"
    Environment = var.environment
    Project     = "the-gaffer"
  }
}

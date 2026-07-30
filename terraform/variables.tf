variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

variable "ec2_instance_type" {
  description = "EC2 instance type for the Gaffer server"
  type        = string
  default     = "t3.small"
}

variable "ec2_key_name" {
  description = "Name of the EC2 key pair for SSH access (must exist in AWS)"
  type        = string
  default     = "gaffer-ec2"
}

variable "ec2_ami_id" {
  description = "Amazon Linux 2023 AMI ID for the Gaffer EC2 instance. Pinned deliberately — bumping this replaces the instance and its root volume, so only change it as part of a planned migration with a backup/snapshot taken first."
  type        = string
  default     = "ami-0c456f2cfcc96df82"
}

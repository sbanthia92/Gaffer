output "elastic_ip" {
  description = "Public Elastic IP — set this as EC2_HOST in GitHub secrets"
  value       = aws_eip.gaffer.public_ip
}

output "domain" {
  description = "Production domain"
  value       = "https://the-gaffer.io"
}

output "ssh_command" {
  description = "SSH command to connect to the server"
  value       = "ssh -i ~/.ssh/gaffer_ec2 ec2-user@${aws_eip.gaffer.public_ip}"
}

output "ecr_repository_url" {
  description = "ECR repository URL (for future ECS/EKS migration)"
  value       = aws_ecr_repository.gaffer_api.repository_url
}

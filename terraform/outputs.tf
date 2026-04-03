output "ecr_repository_url" {
  description = "ECR repository URL for the API image"
  value       = aws_ecr_repository.gaffer_api.repository_url
}

output "ecr_repository_arn" {
  description = "ECR repository ARN"
  value       = aws_ecr_repository.gaffer_api.arn
}

# Uncomment once EKS module is enabled:
# output "eks_cluster_name" {
#   description = "EKS cluster name"
#   value       = module.eks.cluster_name
# }
#
# output "eks_cluster_endpoint" {
#   description = "EKS cluster API endpoint"
#   value       = module.eks.cluster_endpoint
# }

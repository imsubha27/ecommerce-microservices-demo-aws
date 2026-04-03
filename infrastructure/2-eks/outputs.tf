output "cluster_endpoint" {
  description = "The endpoint of the EKS cluster"
  value       = aws_eks_cluster.eks_cluster.endpoint
}

output "cluster_name" {
  description = "The name of the EKS cluster"
  value       = aws_eks_cluster.eks_cluster.name
}

output "cluster_version" {
  description = "The version of the EKS cluster"
  value       = aws_eks_cluster.eks_cluster.version
}
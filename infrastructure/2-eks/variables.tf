variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
  default = "ecommerce-cluster"
}

variable "cluster_version" {
  description = "Version of the EKS cluster"
  type        = string
  default     = "1.35"
}

variable "node_groups" {
  description = "Map of node group configurations"
  type = map(object({
    instance_types = list(string)
    capacity_type  = string
    scaling_config = object({
      desired_size = number
      max_size     = number
      min_size     = number
    })
  }))
  default = {
    default = {
      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
      scaling_config = {
        desired_size = 2
        max_size     = 4
        min_size     = 2
      }
    }
  }
}

# Fetch VPC/subnets from remote state
locals {
  vpc_id             = data.terraform_remote_state.network.outputs.vpc_id
  private_subnet_ids = data.terraform_remote_state.network.outputs.private_subnet_ids
  public_subnet_ids  = data.terraform_remote_state.network.outputs.public_subnet_ids
}

# Create IAM role for EKS cluster
resource "aws_iam_role" "eks_role" {
  name = "${var.cluster_name}-eks-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "eks.amazonaws.com"
        }
      }
    ]
  })
  tags = {
    Name = "${var.cluster_name}-eks-role"
  }
}

# Attach EKS Cluster Policy to the role
resource "aws_iam_role_policy_attachment" "eks_policy_attachment" {
  role       = aws_iam_role.eks_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# Create the EKS cluster
resource "aws_eks_cluster" "eks_cluster" {
  name     = var.cluster_name
  version  = var.cluster_version
  role_arn = aws_iam_role.eks_role.arn

  vpc_config {
    subnet_ids = local.private_subnet_ids
    endpoint_public_access = true
    endpoint_private_access = true
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_policy_attachment
  ]

  tags = {
    Name = var.cluster_name
  }
}



# Create IAM role for EKS worker nodes
resource "aws_iam_role" "eks_node_role" {
  name = "${var.cluster_name}-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
  tags = {
    Name = "${var.cluster_name}-node-role"
  }
}

# Attach necessary policies to the node role
resource "aws_iam_role_policy_attachment" "eks_node_policy_attachment" {
    for_each = toset([
      "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
      "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
      "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
])
    role       = aws_iam_role.eks_node_role.name
    policy_arn = each.value
}

# Create EKS node group
resource "aws_eks_node_group" "eks_node_group" {
    for_each = var.node_groups
    cluster_name = aws_eks_cluster.eks_cluster.name
    node_group_name = each.key
    node_role_arn = aws_iam_role.eks_node_role.arn
    subnet_ids = local.private_subnet_ids
    instance_types = each.value.instance_types
    capacity_type = each.value.capacity_type

    scaling_config {
      desired_size = each.value.scaling_config.desired_size
      max_size     = each.value.scaling_config.max_size
      min_size     = each.value.scaling_config.min_size
    }
    depends_on = [ aws_iam_role_policy_attachment.eks_node_policy_attachment ]
}
locals {
  availability_zones = ["ap-south-1a", "ap-south-1b"]

  public_subnets = [
    "10.0.1.0/24",
    "10.0.2.0/24"
  ]

  private_subnets = [
    "10.0.3.0/24",
    "10.0.4.0/24"
  ]
}


resource "aws_vpc" "eks_vpc" {
  cidr_block = var.vpc_cidr
  enable_dns_support = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.cluster_name}-vpc"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# Public subnets (for ALB, NAT)
resource "aws_subnet" "public_subnet" {
  count = length(local.public_subnets)
  vpc_id = aws_vpc.eks_vpc.id
  cidr_block = local.public_subnets[count.index]
  availability_zone = element(local.availability_zones, count.index)
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.cluster_name}-public-subnet-${count.index + 1}"
    "kubernetes.io/role/elb" = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

# Private subnets (for EKS nodes)
resource "aws_subnet" "private_subnet" {
  count = length(local.private_subnets)
  vpc_id = aws_vpc.eks_vpc.id
  cidr_block = local.private_subnets[count.index]
  availability_zone = element(local.availability_zones, count.index)

  tags = {
    Name = "${var.cluster_name}-private-subnet-${count.index + 1}"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

# Internet Gateway for public subnets
resource "aws_internet_gateway" "eks_igw" {
  vpc_id = aws_vpc.eks_vpc.id

  tags = {
    Name = "${var.cluster_name}-internet-gateway"
  }
}


# NAT Gateway 
# Elastic IP for NAT Gateway
resource "aws_eip" "nat_eip" {
    domain = "vpc"
    tags = {
    Name = "${var.cluster_name}-elastic-ip"
  }
}

resource "aws_nat_gateway" "eks_nat_gateway" {
  allocation_id = aws_eip.nat_eip.id
  subnet_id = aws_subnet.public_subnet[0].id

  tags = {
    Name = "${var.cluster_name}-nat-gateway"
  }
}

# Public route table
resource "aws_route_table" "public_route_table" {
  vpc_id = aws_vpc.eks_vpc.id
  count = length(local.public_subnets)
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.eks_igw.id
    }
    tags = {
        Name = "${var.cluster_name}-public-route-table-${count.index + 1}"
    }
}

resource "aws_route_table_association" "public_route_table_association" {
  count = length(local.public_subnets)
  subnet_id = aws_subnet.public_subnet[count.index].id
  route_table_id = aws_route_table.public_route_table[count.index].id
}


# Private route table
resource "aws_route_table" "private_route_table" {
  vpc_id = aws_vpc.eks_vpc.id
  count = length(local.private_subnets)
  route {
    cidr_block = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.eks_nat_gateway.id
  }

  tags = {
    Name = "${var.cluster_name}-private-route-table-${count.index + 1}"
  }
}

resource "aws_route_table_association" "private_route_table_association" {
  count = length(local.private_subnets)
  subnet_id = aws_subnet.private_subnet[count.index].id
  route_table_id = aws_route_table.private_route_table[count.index].id
}
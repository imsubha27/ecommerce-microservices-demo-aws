# This file defines the data sources for the EKS module, allowing us to reference outputs from the VPC module.

data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = "microservices-demo-27"
    key    = "network/terraform.tfstate"
    region = "ap-south-1"
  }
}
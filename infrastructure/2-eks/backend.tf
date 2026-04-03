terraform {
  backend "s3" {
    bucket = "microservices-demo-27"
    key    = "eks/terraform.tfstate"
    region = "ap-south-1"
    dynamodb_table = "tf-state-lock"
    encrypt        = true
  }
}
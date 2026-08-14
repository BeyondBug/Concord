# Concord demo fixture — intentional violations for real Checkov scanning
# These are real security issues that Checkov catches.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "us-east-1"
}

# VIOLATION CKV_AWS_1: IAM policy with wildcard * actions
resource "aws_iam_role_policy" "overpermissive" {
  name = "concord-demo-bad-policy"
  role = aws_iam_role.app.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"         # Wildcard - should be least privilege
      Resource = "*"         # Wildcard - should be specific ARN
    }]
  })
}

resource "aws_iam_role" "app" {
  name = "concord-demo-app-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# VIOLATION CKV_AWS_18: S3 bucket without access logging
# VIOLATION CKV_AWS_19: S3 bucket without encryption
# VIOLATION CKV_AWS_21: S3 bucket without versioning
resource "aws_s3_bucket" "data" {
  bucket = "concord-demo-data-bucket"
}

# VIOLATION CKV_AWS_25: Security group allows all inbound traffic
resource "aws_security_group" "open" {
  name        = "concord-demo-open-sg"
  description = "Demo security group with violations"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]   # SSH open to world
  }

  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]   # All ports open
  }
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region for deployment"
}

variable "project_name" {
  type        = string
  default     = "studybot"
  description = "Project name tag"
}

variable "environment" {
  type        = string
  default     = "prod"
  description = "Deployment environment"
}

variable "vector_bedrock_kb_id" {
  type        = string
  default     = "ABCD1234" # Dummy fallback, override in terraform.tfvars or env
  description = "AWS Bedrock Knowledge Base ID"
}

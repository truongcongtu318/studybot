# ============================================================================
# StudyBot — AWS Infrastructure (Terraform, NO VPC)
#
# Architecture (Serverless, public endpoints):
#   CloudFront → S3 (static frontend)
#   API Gateway HTTP API → Lambda (FastAPI + Mangum) → Bedrock / DynamoDB / S3
#
# Zero VPC, zero NAT Gateway. Lambda runs outside VPC and accesses all
# AWS services via public endpoints using IAM roles.
# ============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── Random suffix for globally unique names ──
resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  prefix = "${var.project_name}-${var.environment}"
  suffix = random_id.suffix.hex
}

# ============================================================================
# S3 — Document Storage (uploads)
# ============================================================================

resource "aws_s3_bucket" "documents" {
  bucket        = "${local.prefix}-docs-${local.suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ============================================================================
# S3 — Static Frontend
# ============================================================================

resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.prefix}-frontend-${local.suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ============================================================================
# DynamoDB — Single-table (users, docs, vectors, quizzes, flashcards, events)
# ============================================================================

resource "aws_dynamodb_table" "main" {
  name         = "${local.prefix}-table-${local.suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "sk"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ============================================================================
# IAM — Lambda execution role
# ============================================================================

resource "aws_iam_role" "lambda_role" {
  name = "${local.prefix}-lambda-${local.suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# CloudWatch Logs
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# S3 access (document storage)
resource "aws_iam_role_policy" "lambda_s3" {
  name = "s3-access"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:DeleteObject"
      ]
      Resource = [
        aws_s3_bucket.documents.arn,
        "${aws_s3_bucket.documents.arn}/*"
      ]
    }]
  })
}

# DynamoDB access (single-table)
resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "dynamodb-access"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem"
      ]
      Resource = [
        aws_dynamodb_table.main.arn,
        "${aws_dynamodb_table.main.arn}/index/*"
      ]
    }]
  })
}

# Bedrock access (Claude Converse + Bedrock Agent Runtime for Knowledge Base RAG)
resource "aws_iam_role_policy" "lambda_bedrock" {
  name = "bedrock-access"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:Converse"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
          "arn:aws:bedrock:*:*:inference-profile/*",
          "arn:aws:bedrock:*:*:foundation-model/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock-agent-runtime:RetrieveAndGenerate",
          "bedrock-agent-runtime:Retrieve"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestedRegion" = var.aws_region
          }
        }
      }
    ]
  })
}

# Textract access (hybrid OCR fallback)
resource "aws_iam_role_policy" "lambda_textract" {
  name = "textract-access"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["textract:DetectDocumentText"]
      Resource = "*"
    }]
  })
}

# ============================================================================
# Lambda Function
# ============================================================================

resource "aws_lambda_function" "api" {
  function_name = "${local.prefix}-api-${local.suffix}"
  role          = aws_iam_role.lambda_role.arn
  handler       = "src.app.handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 512

  filename         = "${path.module}/../build/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../build/lambda.zip")

  environment {
    variables = {
      STORAGE_BUCKET       = aws_s3_bucket.documents.id
      USERSTORE_TABLE      = aws_dynamodb_table.main.name
      AI_BACKEND           = "bedrock"
      AI_MODEL_ID    = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      STORAGE_BACKEND      = "s3"
      USERSTORE_BACKEND    = "dynamodb"
      VECTOR_BACKEND       = "bedrock_kb"
      VECTOR_BEDROCK_KB_ID = var.vector_bedrock_kb_id
      SERVE_FRONTEND       = "false"
      LOG_LEVEL            = "INFO"
      DEFAULT_USER_ID      = "test-user-001"
      CORS_ORIGINS         = "*"
    }
  }
}

# Allow API Gateway to invoke Lambda
resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ============================================================================
# API Gateway HTTP API → Lambda
# ============================================================================

resource "aws_apigatewayv2_api" "http" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["content-type", "x-user-id"]
    allow_methods     = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_origins     = ["*"]
    max_age           = 300
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.apigw.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_cloudwatch_log_group" "apigw" {
  name              = "/aws/apigateway/${local.prefix}-${local.suffix}"
  retention_in_days = 7
}

# ============================================================================
# CloudFront → S3 Static Frontend
# ============================================================================

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.prefix}-${local.suffix}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "StudyBot Frontend"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 3600
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# S3 bucket policy to allow CloudFront OAC
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })
}

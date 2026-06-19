output "api_gateway_url" {
  description = "Base URL of the API Gateway HTTP API"
  value       = aws_apigatewayv2_stage.prod.invoke_url
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain for the static frontend"
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for the static frontend"
  value       = aws_cloudfront_distribution.frontend.id
}

output "cloudfront_url" {
  description = "Full URL to the StudyBot frontend"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "dynamodb_table" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.main.name
}

output "s3_documents_bucket" {
  description = "S3 bucket for document storage"
  value       = aws_s3_bucket.documents.id
}

output "s3_frontend_bucket" {
  description = "S3 bucket for static frontend"
  value       = aws_s3_bucket.frontend.id
}

output "lambda_function" {
  description = "Lambda function name"
  value       = aws_lambda_function.api.function_name
}

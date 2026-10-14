output "document_bucket_name" {
  value = aws_s3_bucket.documents.id
}

output "document_bucket_arn" {
  value = aws_s3_bucket.documents.arn
}

output "processing_queue_url" {
  value = aws_sqs_queue.processing.url
}

output "processing_queue_arn" {
  value = aws_sqs_queue.processing.arn
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "idempotency_table_name" {
  value = aws_dynamodb_table.idempotency.name
}

output "kms_key_arn" {
  value = aws_kms_key.pipeline.arn
}

output "api_role_arn" {
  value = aws_iam_role.api.arn
}

output "worker_role_arn" {
  value = aws_iam_role.worker.arn
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "processing_queue_name" {
  value = aws_sqs_queue.processing.name
}

output "dlq_name" {
  value = aws_sqs_queue.dlq.name
}

output "worker_policy_statements" {
  description = "Worker IAM statements used by least-privilege tests."
  value       = local.worker_policy_statements
}

output "api_log_group_name" {
  value = aws_cloudwatch_log_group.api.name
}

output "worker_log_group_name" {
  value = aws_cloudwatch_log_group.worker.name
}

output "bucket_wrong_kms_condition" {
  description = "Condition operator used by DenyWrongKmsKey."
  value       = local.bucket_wrong_kms_condition
}

output "bucket_header_required_deny_present" {
  description = "False when the bucket policy does not require SSE headers on PutObject."
  value       = local.bucket_header_required_deny_present
}

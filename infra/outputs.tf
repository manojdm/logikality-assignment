output "document_bucket_name" {
  value = module.document_pipeline.document_bucket_name
}

output "document_bucket_arn" {
  value = module.document_pipeline.document_bucket_arn
}

output "processing_queue_url" {
  value = module.document_pipeline.processing_queue_url
}

output "processing_queue_arn" {
  value = module.document_pipeline.processing_queue_arn
}

output "dlq_arn" {
  value = module.document_pipeline.dlq_arn
}

output "idempotency_table_name" {
  value = module.document_pipeline.idempotency_table_name
}

output "kms_key_arn" {
  value = module.document_pipeline.kms_key_arn
}

output "api_role_arn" {
  value = module.document_pipeline.api_role_arn
}

output "worker_role_arn" {
  value = module.document_pipeline.worker_role_arn
}

output "alerts_topic_arn" {
  value = module.document_pipeline.alerts_topic_arn
}

output "github_deploy_role_arn" {
  value       = try(module.github_oidc[0].deploy_role_arn, null)
  description = "Present only when enable_github_oidc is true."
}

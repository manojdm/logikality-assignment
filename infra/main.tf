module "document_pipeline" {
  source = "./modules/document-pipeline"

  project_name               = var.project_name
  environment                = var.environment
  aws_region                 = var.aws_region
  max_receive_count          = var.max_receive_count
  visibility_timeout         = var.visibility_timeout
  age_threshold_seconds      = var.age_threshold_seconds
  alert_email                = var.alert_email
  enable_access_logging      = var.enable_access_logging
  enable_object_lock         = var.enable_object_lock
  noncurrent_expiration_days = var.noncurrent_expiration_days
  processed_transition_days  = var.processed_transition_days
  permissions_boundary_arn   = var.permissions_boundary_arn
  log_retention_days         = var.log_retention_days
}

module "github_oidc" {
  count  = var.enable_github_oidc ? 1 : 0
  source = "./modules/github-oidc"

  project_name         = var.project_name
  environment          = var.environment
  github_org           = var.github_org
  github_repo          = var.github_repo
  ecs_cluster_name     = var.ecs_cluster_name
  ecs_service_name     = var.ecs_service_name
  api_task_role_arn    = module.document_pipeline.api_role_arn
  worker_task_role_arn = module.document_pipeline.worker_role_arn
}

variable "project_name" {
  description = "Short name used as a prefix for OIDC and ECR resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "github_org" {
  description = "GitHub organisation allowed to assume the deploy role."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository allowed to assume the deploy role."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster the deploy role may update."
  type        = string
}

variable "ecs_service_name" {
  description = "ECS service the deploy role may update."
  type        = string
}

variable "api_task_role_arn" {
  description = "API task role ARN the deploy role may pass."
  type        = string
}

variable "worker_task_role_arn" {
  description = "Worker task role ARN the deploy role may pass."
  type        = string
}

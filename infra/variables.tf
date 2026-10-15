variable "project_name" {
  description = "Short name used as a prefix for all resources."
  type        = string
  default     = "logikality"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "project_name must be 2-21 lowercase letters, digits or hyphens and start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Tag value identifying the owning team."
  type        = string
  default     = "founding-devops"
}

variable "allowed_account_ids" {
  description = "Optional allow-list that prevents applying this stack to the wrong account."
  type        = list(string)
  default     = []
}

variable "max_receive_count" {
  description = "SQS receive attempts before a message is moved to the DLQ."
  type        = number
  default     = 5

  validation {
    condition     = var.max_receive_count >= 1 && var.max_receive_count <= 10
    error_message = "max_receive_count must be between 1 and 10."
  }
}

variable "visibility_timeout" {
  description = "SQS visibility timeout in seconds. Target ~6x p99 processing time."
  type        = number
  default     = 300

  validation {
    condition     = var.visibility_timeout >= 0 && var.visibility_timeout <= 43200
    error_message = "visibility_timeout must be between 0 and 43200 seconds."
  }
}

variable "age_threshold_seconds" {
  description = "CloudWatch alarm threshold for ApproximateAgeOfOldestMessage."
  type        = number
  default     = 900
}

variable "alert_email" {
  description = "Optional email subscription on the alerts SNS topic."
  type        = string
  default     = ""
}

variable "enable_access_logging" {
  description = "Create a separate access-log bucket and enable S3 server access logging."
  type        = bool
  default     = true
}

variable "enable_object_lock" {
  description = "WORM lock for compliance. Can only be enabled at bucket creation."
  type        = bool
  default     = false
}

variable "noncurrent_expiration_days" {
  description = "Days to keep noncurrent object versions. Mortgage retention may require longer."
  type        = number
  default     = 90
}

variable "processed_transition_days" {
  description = "Days before processed/ objects transition to STANDARD_IA."
  type        = number
  default     = 30
}

variable "permissions_boundary_arn" {
  description = "Optional IAM permissions boundary applied to task roles."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for API and worker log groups."
  type        = number
  default     = 365
}

variable "enable_compute" {
  description = "Provision a demo VPC, ALB, ECR and ECS Fargate API + worker. Off by default."
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Full image URI for ECS tasks. Empty creates ECR/ALB/cluster only."
  type        = string
  default     = ""
}

variable "enable_github_oidc" {
  description = "Create the GitHub Actions OIDC provider, deploy role and ECR repository."
  type        = bool
  default     = false
}

variable "github_org" {
  description = "GitHub organisation that may assume the deploy role via OIDC."
  type        = string
  default     = "example-org"
}

variable "github_repo" {
  description = "GitHub repository that may assume the deploy role via OIDC."
  type        = string
  default     = "logikality"
}

variable "ecs_cluster_name" {
  description = "ECS cluster name referenced by the deploy IAM policy."
  type        = string
  default     = "logikality"
}

variable "ecs_service_name" {
  description = "ECS service name referenced by the deploy IAM policy."
  type        = string
  default     = "docproc"
}

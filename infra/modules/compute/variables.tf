variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "container_image" {
  description = "ECR image URI including tag. Empty skips ECS services until the first image is pushed."
  type        = string
  default     = ""
}

variable "api_task_role_arn" {
  type = string
}

variable "worker_task_role_arn" {
  type = string
}

variable "document_bucket" {
  type = string
}

variable "queue_url" {
  type = string
}

variable "idempotency_table" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "api_log_group_name" {
  type = string
}

variable "worker_log_group_name" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "service_name" {
  type = string
}

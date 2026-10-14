variable "project_name" {
  description = "Short name used as a prefix for all resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, or prod)."
  type        = string
}

variable "aws_region" {
  description = "AWS region for module resources."
  type        = string
}

variable "max_receive_count" {
  description = "SQS receive attempts before a message is moved to the DLQ."
  type        = number

  validation {
    condition     = var.max_receive_count >= 1 && var.max_receive_count <= 10
    error_message = "max_receive_count must be between 1 and 10."
  }
}

variable "visibility_timeout" {
  description = "SQS visibility timeout in seconds. Must be between 0 and 43200."
  type        = number

  validation {
    condition     = var.visibility_timeout >= 0 && var.visibility_timeout <= 43200
    error_message = "visibility_timeout must be between 0 and 43200 seconds."
  }
}

variable "age_threshold_seconds" {
  description = "CloudWatch alarm threshold for ApproximateAgeOfOldestMessage."
  type        = number

  validation {
    condition     = var.age_threshold_seconds >= 1
    error_message = "age_threshold_seconds must be at least 1."
  }
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
  description = "Days to keep noncurrent object versions."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_expiration_days >= 1
    error_message = "noncurrent_expiration_days must be at least 1."
  }
}

variable "processed_transition_days" {
  description = "Days before processed/ objects transition to STANDARD_IA."
  type        = number
  default     = 30

  validation {
    condition     = var.processed_transition_days >= 1
    error_message = "processed_transition_days must be at least 1."
  }
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

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch Logs allowed retention value."
  }
}

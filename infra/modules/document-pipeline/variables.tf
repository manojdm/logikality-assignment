variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "max_receive_count" {
  type = number
}

variable "visibility_timeout" {
  type = number
}

variable "age_threshold_seconds" {
  type = number
}

variable "alert_email" {
  type    = string
  default = ""
}

variable "enable_access_logging" {
  type    = bool
  default = true
}

variable "enable_object_lock" {
  type    = bool
  default = false
}

variable "noncurrent_expiration_days" {
  type    = number
  default = 90
}

variable "processed_transition_days" {
  type    = number
  default = 30
}

variable "permissions_boundary_arn" {
  type    = string
  default = ""
}

variable "log_retention_days" {
  type    = number
  default = 365
}

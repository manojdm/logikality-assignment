data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  prefix      = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
  partition   = data.aws_partition.current.partition
  region      = var.aws_region
  bucket_name = "${local.prefix}-docs-${local.account_id}"
  logs_name   = "${local.prefix}-docs-logs-${local.account_id}"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  prefix     = "${var.project_name}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = var.aws_region
  # Region is in the name so a destroy+recreate in another region does not
  # hang on S3's global name hold (often 30–60+ minutes after DeleteBucket).
  bucket_name = "${local.prefix}-docs-${local.account_id}-${local.region}"
  logs_name   = "${local.prefix}-docs-logs-${local.account_id}-${local.region}"
}

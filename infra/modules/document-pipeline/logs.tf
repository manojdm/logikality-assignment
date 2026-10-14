resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.prefix}/api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.pipeline.arn
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.prefix}/worker"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.pipeline.arn
}

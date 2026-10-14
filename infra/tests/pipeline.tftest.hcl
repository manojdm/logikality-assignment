mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:root"
      user_id    = "AIDATEST"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition  = "aws"
      dns_suffix = "amazonaws.com"
    }
  }

  mock_data "aws_region" {
    defaults = {
      id   = "us-east-1"
      name = "us-east-1"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"LeastPrivilege\",\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\"],\"Resource\":[\"arn:aws:s3:::example/incoming/*\"]}]}"
    }
  }
}

run "pipeline_security_defaults" {
  command = plan

  module {
    source = "./modules/document-pipeline"
  }

  variables {
    project_name               = "logikality"
    environment                = "dev"
    aws_region                 = "us-east-1"
    max_receive_count          = 5
    visibility_timeout         = 300
    age_threshold_seconds      = 900
    enable_access_logging      = true
    enable_object_lock         = false
    noncurrent_expiration_days = 90
    processed_transition_days  = 30
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.documents.block_public_acls == true
    error_message = "block_public_acls must be true"
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.documents.block_public_policy == true
    error_message = "block_public_policy must be true"
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.documents.ignore_public_acls == true
    error_message = "ignore_public_acls must be true"
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.documents.restrict_public_buckets == true
    error_message = "restrict_public_buckets must be true"
  }

  assert {
    condition = alltrue([
      for rule in aws_s3_bucket_server_side_encryption_configuration.documents.rule :
      rule.apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
    ])
    error_message = "document bucket must use aws:kms"
  }

  assert {
    condition     = aws_sqs_queue.processing.receive_wait_time_seconds == 20
    error_message = "processing queue must use long polling (20s)"
  }

  assert {
    condition     = aws_sqs_queue.processing.visibility_timeout_seconds == 300
    error_message = "visibility timeout must match the 300s default"
  }

  assert {
    condition     = aws_kms_key.pipeline.enable_key_rotation == true
    error_message = "CMK rotation must be enabled"
  }

  assert {
    condition     = aws_s3_bucket.documents.force_destroy == false
    error_message = "document bucket must not force-destroy"
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.queue_oldest_message_age.threshold == 900
    error_message = "queue-age alarm threshold must be 900s"
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.dlq_messages_visible.statistic == "Maximum"
    error_message = "DLQ alarm must use Maximum"
  }

  assert {
    condition = alltrue([
      for stmt in local.worker_policy_statements : (
        alltrue([for a in stmt.actions : !strcontains(a, "*")]) &&
        alltrue([for r in stmt.resources : r != "*"])
      )
    ])
    error_message = "worker IAM must not use wildcard actions or Resource *"
  }

  assert {
    condition     = contains(flatten([for s in local.worker_policy_statements : s.actions]), "dynamodb:DeleteItem")
    error_message = "worker must be allowed to DeleteItem to release IN_PROGRESS claims"
  }

  assert {
    condition     = local.bucket_header_required_deny_present == false
    error_message = "bucket policy must not require SSE headers; default encryption already applies the CMK"
  }

  assert {
    condition     = local.bucket_wrong_kms_condition == "StringNotEqualsIfExists"
    error_message = "DenyWrongKmsKey must use StringNotEqualsIfExists"
  }

  assert {
    condition     = aws_cloudwatch_log_group.api.name == "/ecs/logikality-dev/api"
    error_message = "API log group name must match the runbook Logs Insights path"
  }
}

run "reject_invalid_environment" {
  command = plan

  variables {
    environment  = "qa"
    project_name = "logikality"
  }

  expect_failures = [
    var.environment,
  ]
}

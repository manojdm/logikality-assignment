data "aws_iam_policy_document" "ecs_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:ecs:${local.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "api" {
  name                 = "${local.prefix}-api-task"
  assume_role_policy   = data.aws_iam_policy_document.ecs_trust.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null
}

resource "aws_iam_role" "worker" {
  name                 = "${local.prefix}-worker-task"
  assume_role_policy   = data.aws_iam_policy_document.ecs_trust.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "PutIncomingObjects"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/incoming/*"]
  }

  statement {
    # HeadBucket requires s3:ListBucket on the bucket ARN. Scoped to this
    # bucket so /ready can probe without listing object contents.
    sid       = "HeadBucketForReadiness"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
  }

  statement {
    sid       = "EnqueueDocuments"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.processing.arn]
  }

  statement {
    sid = "KmsForS3AndSqs"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.pipeline.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "s3.${local.region}.amazonaws.com",
        "sqs.${local.region}.amazonaws.com",
      ]
    }
  }
}

locals {
  # Known-at-plan resource ARNs so terraform tests can assert least privilege
  # without depending on mocked aws_iam_policy_document JSON.
  worker_policy_statements = [
    {
      sid       = "ReadIncoming"
      actions   = ["s3:GetObject"]
      resources = ["arn:${local.partition}:s3:::${local.bucket_name}/incoming/*"]
    },
    {
      sid       = "WriteProcessed"
      actions   = ["s3:PutObject"]
      resources = ["arn:${local.partition}:s3:::${local.bucket_name}/processed/*"]
    },
    {
      sid = "ConsumeQueue"
      actions = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes",
      ]
      resources = ["arn:${local.partition}:sqs:${local.region}:${local.account_id}:${local.prefix}-processing"]
    },
    {
      sid = "IdempotencyTable"
      actions = [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:GetItem",
        "dynamodb:DeleteItem",
      ]
      resources = ["arn:${local.partition}:dynamodb:${local.region}:${local.account_id}:table/${local.prefix}-idempotency"]
    },
  ]
  bucket_wrong_kms_condition          = "StringNotEqualsIfExists"
  bucket_header_required_deny_present = false
}

data "aws_iam_policy_document" "worker" {
  dynamic "statement" {
    for_each = local.worker_policy_statements
    content {
      sid       = statement.value.sid
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }

  statement {
    sid = "KmsForS3SqsDynamo"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.pipeline.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "s3.${local.region}.amazonaws.com",
        "sqs.${local.region}.amazonaws.com",
        "dynamodb.${local.region}.amazonaws.com",
      ]
    }
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${local.prefix}-api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "${local.prefix}-worker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

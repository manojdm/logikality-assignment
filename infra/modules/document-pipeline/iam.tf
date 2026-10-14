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

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "ReadIncoming"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.documents.arn}/incoming/*"]
  }

  statement {
    sid       = "WriteProcessed"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/processed/*"]
  }

  statement {
    sid = "ConsumeQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.processing.arn]
  }

  statement {
    sid = "IdempotencyTable"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:GetItem",
    ]
    resources = [aws_dynamodb_table.idempotency.arn]
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

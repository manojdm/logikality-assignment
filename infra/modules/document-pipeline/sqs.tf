resource "aws_sqs_queue" "dlq" {
  # checkov:skip=CKV_AWS_27:Encrypted with the customer-managed CMK below.
  name                              = "${local.prefix}-processing-dlq"
  message_retention_seconds         = 1209600
  kms_master_key_id                 = aws_kms_key.pipeline.arn
  kms_data_key_reuse_period_seconds = 300
}

resource "aws_sqs_queue" "processing" {
  # checkov:skip=CKV_AWS_27:Encrypted with the customer-managed CMK below.
  name                              = "${local.prefix}-processing"
  visibility_timeout_seconds        = var.visibility_timeout
  receive_wait_time_seconds         = 20
  message_retention_seconds         = 345600
  kms_master_key_id                 = aws_kms_key.pipeline.arn
  kms_data_key_reuse_period_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.processing.arn]
  })
}

data "aws_iam_policy_document" "processing_queue" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["sqs:*"]
    resources = [aws_sqs_queue.processing.arn]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "dlq" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["sqs:*"]
    resources = [aws_sqs_queue.dlq.arn]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "processing" {
  queue_url = aws_sqs_queue.processing.id
  policy    = data.aws_iam_policy_document.processing_queue.json
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  policy    = data.aws_iam_policy_document.dlq.json
}

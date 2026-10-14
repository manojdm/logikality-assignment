data "aws_iam_policy_document" "kms" {
  # checkov:skip=CKV_AWS_111:KMS key policies use Resource "*" to mean this key; IAM still gates callers.
  # checkov:skip=CKV_AWS_109:Account root must be allowed so administrators can manage grants via IAM.
  # checkov:skip=CKV_AWS_356:Same as above — "*" in a key policy scopes to this CMK, not every key in the account.
  statement {
    sid     = "EnableRootAccountAdministration"
    actions = ["kms:*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
    resources = ["*"]
  }

  statement {
    sid = "AllowSQS"
    principals {
      type        = "Service"
      identifiers = ["sqs.amazonaws.com"]
    }
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid = "AllowSNSAndCloudWatch"
    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com", "cloudwatch.amazonaws.com"]
    }
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_kms_key" "pipeline" {
  description             = "CMK for ${local.prefix} document pipeline (S3, SQS, DynamoDB, SNS)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms.json
}

resource "aws_kms_alias" "pipeline" {
  name          = "alias/${local.prefix}-pipeline"
  target_key_id = aws_kms_key.pipeline.key_id
}

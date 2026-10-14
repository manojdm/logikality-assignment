resource "aws_s3_bucket" "documents" {
  # checkov:skip=CKV_AWS_144:Single-region assessment stack; CRR is a documented future control.
  # checkov:skip=CKV2_AWS_62:Event notifications are not required; workers consume SQS, not S3 events.
  bucket        = local.bucket_name
  force_destroy = false

  object_lock_enabled = var.enable_object_lock
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.pipeline.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-noncurrent"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_expiration_days
    }
  }

  rule {
    id     = "processed-to-ia"
    status = "Enabled"
    filter {
      prefix = "processed/"
    }
    transition {
      days          = var.processed_transition_days
      storage_class = "STANDARD_IA"
    }
  }
}

data "aws_iam_policy_document" "documents" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.documents.arn,
      "${aws_s3_bucket.documents.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyUnencryptedOrWrongKey"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid    = "DenyWrongKmsKey"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.pipeline.arn]
    }
  }

  # Future: deny Put/Get unless the request comes through the S3 VPC gateway
  # endpoint. Uncomment after private networking is in place.
  # statement {
  #   sid    = "DenyOutsideVpcEndpoint"
  #   effect = "Deny"
  #   principals {
  #     type        = "*"
  #     identifiers = ["*"]
  #   }
  #   actions   = ["s3:*"]
  #   resources = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
  #   condition {
  #     test     = "StringNotEquals"
  #     variable = "aws:SourceVpce"
  #     values   = [var.s3_vpc_endpoint_id]
  #   }
  # }
}

resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = data.aws_iam_policy_document.documents.json

  depends_on = [aws_s3_bucket_public_access_block.documents]
}

resource "aws_s3_bucket" "logs" {
  # checkov:skip=CKV_AWS_144:Log bucket stays in-region; CRR is a future control.
  # checkov:skip=CKV_AWS_18:Server access logging of the log bucket itself would recurse.
  # checkov:skip=CKV2_AWS_62:Event notifications not required for access logs.
  # checkov:skip=CKV_AWS_145:S3 log delivery cannot write KMS-encrypted objects; AES256 is required.
  count         = var.enable_access_logging ? 1 : 0
  bucket        = local.logs_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "logs" {
  count                   = var.enable_access_logging ? 1 : 0
  bucket                  = aws_s3_bucket.logs[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  count  = var.enable_access_logging ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  count  = var.enable_access_logging ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  # SSE-S3 is required: S3 log delivery cannot write KMS-encrypted objects.
  count  = var.enable_access_logging ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  count  = var.enable_access_logging ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id
  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.log_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "logs" {
  count = var.enable_access_logging ? 1 : 0
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.logs[0].arn,
      "${aws_s3_bucket.logs[0].arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid = "AllowS3LogDelivery"
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs[0].arn}/*"]
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.documents.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  count  = var.enable_access_logging ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id
  policy = data.aws_iam_policy_document.logs[0].json

  depends_on = [aws_s3_bucket_public_access_block.logs]
}

resource "aws_s3_bucket_logging" "documents" {
  count         = var.enable_access_logging ? 1 : 0
  bucket        = aws_s3_bucket.documents.id
  target_bucket = aws_s3_bucket.logs[0].id
  target_prefix = "s3-access/"
}

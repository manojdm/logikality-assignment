resource "aws_dynamodb_table" "idempotency" {
  # checkov:skip=CKV_AWS_119:SSE is configured with the customer-managed CMK.
  name                        = "${local.prefix}-idempotency"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  deletion_protection_enabled = var.environment == "prod"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.pipeline.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

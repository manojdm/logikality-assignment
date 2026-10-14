# Credentials come from the environment (AWS_PROFILE=<your-profile> locally,
# GitHub OIDC in CI). The profile is intentionally not hardcoded so the
# same configuration works for every operator and pipeline.
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = length(var.allowed_account_ids) > 0 ? var.allowed_account_ids : null

  default_tags {
    tags = {
      Project            = var.project_name
      Environment        = var.environment
      ManagedBy          = "terraform"
      Owner              = var.owner
      DataClassification = "confidential"
    }
  }
}

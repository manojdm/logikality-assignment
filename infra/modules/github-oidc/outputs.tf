output "deploy_role_arn" {
  value = aws_iam_role.deploy.arn
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

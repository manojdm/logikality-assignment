# Secure deploy, failure handling, and rollback

`deploy.yml` is a **reference** workflow. It is gated on `vars.DEPLOY_ENABLED == 'true'` so a default clone never talks to AWS.

## Secure deploy

- **OIDC, not access keys.** `aws-actions/configure-aws-credentials` assumes the role created by `modules/github-oidc`. The trust policy pins `aud=sts.amazonaws.com` and `sub=repo:<org>/<repo>:environment:<env>`.
- **Separate AWS accounts per environment.** Staging credentials cannot mutate prod.
- **Build once, promote the digest.** CI pushes `sha-<7>` (and a semver tag on `v*` releases) to GHCR/ECR. Deploy never rebuilds. `latest` is not used as a deploy reference.
- **Environment protection.** GitHub `environment: staging` then `production` with required reviewers.
- **Image signing.** Next hardening step: cosign keyless (Sigstore) at push, verified in the deploy job before `ecs update-service`.
- **Secrets.** Database credentials and OCR API keys live in Secrets Manager / SSM and are injected via the task definition. They never sit in GitHub secrets besides the OIDC role ARN as a variable.
- **Terraform apply** is a separate gated pipeline (commented `plan` job in `terraform.yml`), not mixed into the application deploy.

## Image tagging strategy

| Tag | When | Used for deploy? |
| --- | --- | --- |
| `sha-<7>` | every build | **yes** — immutable pointer to a git commit |
| `pr-<n>` | pull requests | no (image is loaded locally for smoke, not pushed) |
| `main` | push to main | convenience only |
| `1.2.3` / `1.2` | git `v*` tags | production promotions |
| `latest` | never | no |

Immutability pairs with ECR `image_tag_mutability = IMMUTABLE`. Rollback is "deploy the previous sha", not "retarget latest".

## Failure handling

- ECS deployment circuit breaker with `rollback = true`.
- ALB health checks hit `/health` (liveness, no downstream calls). ECS container health and ALB target group health both have to go green. Readiness is `/ready` and is what post-deploy smoke tests.
- `minimumHealthyPercent = 100`, `maximumPercent = 200` so a bad revision never replaces every healthy task.
- CloudWatch alarms (queue age, 5xx on the ALB) attached as ECS deployment alarms trigger auto-rollback.
- Optional next step for the API: CodeDeploy blue/green, canary `10Percent5Minutes`.
- Workers roll safely: on SIGTERM they stop polling, finish the in-flight batch, and exit. Unfinished messages become visible after the visibility timeout. DynamoDB idempotency prevents double-processing.

## Manual rollback (within 5 minutes)

**Option A — GitHub Actions.** Re-run `deploy.yml` (`workflow_dispatch`) with the previous `sha-<7>` tag.

**Option B — CLI.**

```bash
PREV=$(aws ecs describe-services --cluster logikality --services docproc \
  --query 'services[0].deployments[?status==`PRIMARY`].taskDefinition' --output text)
# or pick a known-good revision from
aws ecs list-task-definitions --family-prefix docproc --sort DESC
aws ecs update-service --cluster logikality --service docproc \
  --task-definition docproc:<previous> --force-new-deployment
```

Verify `/ready` returns 200 and `ApproximateAgeOfOldestMessage` is not climbing.

## Database migrations

Expand/contract: add the new column nullable, deploy code that dual-writes, backfill, then switch reads, then drop the old column in a later change. Rollbacks never require a schema downgrade.

## Terraform rollback

Revert the git commit and re-apply. S3 state versioning (see `backend.tf.example`) lets us recover a corrupted state file. Never `terraform apply` a hand-edited state.

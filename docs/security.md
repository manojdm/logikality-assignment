# Security notes

## Threat model (mortgage documents = PII / confidential)

| Threat | Control |
| --- | --- |
| Public bucket / ACL leak | Block Public Access (all four), BucketOwnerEnforced, no ACLs |
| Data at rest | Customer-managed KMS CMK, rotation on, S3 bucket keys (cost + blast-radius) |
| Data in transit | Bucket/queue policies `aws:SecureTransport=false` deny |
| Unencrypted PutObject | Deny unless `x-amz-server-side-encryption=aws:kms` and the pipeline key |
| Over-privileged app | Split API vs worker IAM roles, no `s3:*`, no `Resource *` except object prefixes |
| Confused-deputy on ECS | Trust policy `aws:SourceAccount` + `ArnLike aws:SourceArn` |
| Long-lived CI keys | GitHub OIDC; deploy role scoped to one ECR repo and one ECS service |
| Secret in git | gitleaks in pre-commit and CI; `.gitignore` for `.env` / `*.tfvars` / tfstate |
| Image drift | Immutable tags, Trivy in CI, Dependabot for Docker/pip/actions/terraform |
| Retry-amplified cost | DLQ, bounded `maxReceiveCount`, KMS data-key reuse, long polling, bucket keys |

## Liveness vs readiness

`/health` never calls AWS. An SQS/S3 outage must not restart-loop the API. `/ready` does `HeadBucket` + `GetQueueAttributes` and is what the load balancer / deploy smoke test uses.

## IAM decision: HeadBucket

`HeadBucket` is authorised by `s3:ListBucket` on the **bucket ARN** (not `/*`). The API role is granted that action on this bucket only so `/ready` works. It is not granted `s3:GetObject` or `s3:ListBucket` with a broad prefix.

## Checkov skips (justified)

Recorded inline next to the resource as `# checkov:skip=CKV_...:<reason>`:

| ID | Resource | Reason |
| --- | --- | --- |
| CKV_AWS_144 | S3 buckets | Cross-region replication is a future DR control; single-region assessment. |
| CKV2_AWS_62 | S3 buckets | Event notifications unused; workers consume SQS. |
| CKV_AWS_18 | Log bucket | Logging the log bucket would recurse. |
| CKV_AWS_27 | SQS | Encrypted with the customer-managed CMK (`kms_master_key_id`). |
| CKV_AWS_119 | DynamoDB | SSE configured with the CMK. |
| CKV_AWS_136 | ECR | Uses the AWS-managed ECR KMS key; dedicated CMK is a follow-up. |
| CKV_AWS_145 | Log bucket | S3 access-log delivery cannot write KMS-encrypted objects; AES256 is required. |
| CKV_AWS_111 / 109 / 356 | KMS key policy | A CMK policy Resource of `"*"` means this key. Root must retain `kms:*` so IAM can grant use. |

Any new skip must be added here.

## Action pinning

Workflows pin GitHub Actions to **major version tags** (`@v4`). SHA-pinning is the hardening step; Dependabot is configured to keep those tags current. Do not invent SHAs. To pin:

```bash
gh api repos/actions/checkout/git/ref/tags/v4 --jq .object.sha
```

## Image scan notes

`trivy image` on `logikality-docproc:local` reported HIGH (not CRITICAL) findings in transitive/pinned libraries, notably `python-multipart` (bumped to 0.0.30) and `starlette` (pinned by FastAPI). Dependabot is configured to open weekly PRs for pip and Docker. CI fails the build on **unfixed CRITICAL** only, which matches a founding-team risk appetite for an assessment image.

## Profile `vaidra`

`providers.tf` does **not** hardcode a profile. Locally: `export AWS_PROFILE=vaidra`. CI: OIDC. Never commit `~/.aws`, access keys, or `*.tfvars`.

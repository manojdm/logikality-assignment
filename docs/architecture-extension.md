# Extending the architecture

The Terraform in `infra/` provisions storage, messaging, encryption, IAM and alarms. Compute, a relational database and production networking are **intentionally not applied** (the brief forbids live cost). This note is the design we would implement next.

## Compute: ECS Fargate (not EKS, not Lambda)

| Option | Why not first |
| --- | --- |
| Lambda | 15-minute hard limit, 6 MB synchronous payload, and awkward large-file OCR/LLM jobs. Cold starts hurt p99 ingest. |
| EKS | A two-person founding team should not run a control plane, node groups, and cluster upgrades for a single service. |
| ECS on EC2 | Capacity management without a benefit we need yet. |

**Fargate** gives us task-level isolation, IAM task roles we already defined (`api-task`, `worker-task`), and no nodes.

- **API service:** on-demand Fargate behind an ALB. Target tracking on CPU (70%) and request count. Deployment circuit breaker `enable=true`, `rollback=true`. `minimumHealthyPercent=100`, `maximumPercent=200`.
- **Worker service:** Fargate Spot (safe because processing is idempotent). Scale on a custom metric `ApproximateNumberOfMessagesVisible / RunningTaskCount` targeting ~5 messages per task, with a hard `maxCapacity` so a retry storm cannot explode cost.
- One image, two commands: `uvicorn ...` and `python -m docproc.worker`. SIGTERM handling in the worker finishes the in-flight batch; leftover messages become visible again.

## Database: RDS PostgreSQL (or Aurora Serverless v2)

DynamoDB stays the hot idempotency store (single-digit millisecond conditional writes, TTL). Job metadata, audit history and originator records move to Postgres.

- Multi-AZ, private data subnets only, storage encrypted with the pipeline CMK.
- IAM database authentication **or** Secrets Manager rotation (not both on day one; pick Secrets Manager + RDS Proxy).
- Automated backups, PITR, `deletion_protection` in prod, Performance Insights, parameter group forcing `rds.force_ssl=1`.
- RDS Proxy in front of the worker tasks so concurrent processors do not exhaust connections.
- Schema migrations use the expand/contract pattern so application rollbacks never require a schema rollback.

## Networking

- `/16` VPC across three AZs.
- Public subnets: ALB, NAT (one NAT per AZ in prod; single NAT is acceptable in staging).
- Private app subnets: ECS tasks.
- Private data subnets: RDS. No internet route.
- Gateway VPC endpoints for S3 and DynamoDB; interface endpoints for SQS, ECR (api + dkr), Logs, KMS, STS, Secrets Manager. This cuts NAT data-processing cost (a common driver of the "costs are rising" incident) and keeps PII off the public internet.
- Security groups chained: ALB SG → API SG (8080) → RDS SG (5432). Worker SG talks to SQS/S3/DDB via endpoints, not to the ALB.
- AWS WAF on the ALB (managed core rule set + rate limit). ACM certificate, HTTPS only, HTTP redirected.
- VPC Flow Logs to the log bucket.

## Accounts, state, environments

- AWS Organizations: `prod`, `nonprod`, `security/log-archive`. SCPs deny leaving GuardDuty/CloudTrail off and deny creating IAM users with access keys in prod.
- Remote state in the security account: S3 + `use_lockfile`, KMS, versioning. See `infra/backend.tf.example`.
- Same module, separate state files per environment (`dev` / `staging` / `prod`). Promotion is a module version bump, not a copy-paste.
- AWS Budgets + Cost Anomaly Detection on SQS, KMS, NAT, Fargate and the OCR/LLM vendor.

## Sequence we would actually ship

1. VPC + endpoints + KMS (already in this repo).
2. ECS cluster, task definitions using the existing role ARNs, ALB, WAF.
3. RDS + proxy, migrate idempotency if needed.
4. GitHub OIDC module (`enable_github_oidc=true`) and the gated `deploy.yml`.
5. Autoscaling, dashboards, the two (plus retry-ratio) alarms already defined.

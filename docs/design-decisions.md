# Design decisions

| Decision | Why |
| --- | --- |
| Python / FastAPI | Fast to test, first-class typing, boto3, matches a small founding team. |
| One image, two commands | API and worker stay version-aligned; rollback is one digest. |
| Liveness ≠ readiness | Downstream outages must not restart-loop the process. |
| Split IAM roles | API cannot read documents or consume the queue; worker cannot send. |
| CMK vs SSE-S3 | Control + rotation + CloudTrail on key use. Cost is mitigated with S3 bucket keys and SQS data-key reuse (300s). |
| Long polling (20s) | Cuts empty receives (a real SQS cost line-item) and is the AWS default recommendation. |
| Visibility 300s | ~6× expected stub processing; heartbeats would be added for real OCR jobs. |
| DLQ `maxReceiveCount=5` | Bounded retries. Permanent errors shorten visibility so poison messages hit the DLQ quickly. |
| Lease-based DynamoDB idempotency | Conditional `PutItem` succeeds when the item is missing **or** `IN_PROGRESS` with an expired lease. `release()` (`DeleteItem`) on transient/permanent errors so a crash cannot strand a document for the 7-day TTL. |
| FIFO not chosen | Throughput limits and the workload does not require ordering. Dedup is application-level. |
| Fargate next | See `architecture-extension.md`. Lambda's 15-minute cap is a poor fit for mortgage OCR. |
| Tag `sha-<7>`, never `latest` | Traceability, immutability, trivial rollback. |
| OIDC | No long-lived AWS keys in GitHub. |
| `Idempotency-Key` header | Optional. `document_id = uuid5(namespace, key)` so a client retry after a 5xx does not create a duplicate object. |
| Scan-before-push | CI loads `docproc:scan`, smokes it, runs Trivy, then pushes (cache hit) only on non-PR events. |
| LocalStack e2e | $0 demonstration that the async path actually works. |

#!/usr/bin/env python3
"""Render the current-state architecture to architecture.png (repo root).

Source of truth for the editable diagram. Every component and label below is
traceable to infra/modules/document-pipeline/*.tf or app/src/docproc/*.py;
anything else is drawn with the PROPOSED style.

    python docs/diagrams/architecture.py   # or: make diagram
"""

from __future__ import annotations

from pathlib import Path

from svgkit import FAINT, INK, MUTED, PROPOSED, WARN, Svg, legend_swatch

ROOT = Path(__file__).resolve().parents[2]
SVG_OUT = Path(__file__).with_suffix(".svg")
PNG_OUT = ROOT / "architecture.png"

BOLD = {"weight": "bold", "color": INK}
RED = {"color": WARN}
RED_BOLD = {"weight": "bold", "color": WARN}
ORANGE = {"color": PROPOSED}


def header(s: Svg) -> None:
    s.text(
        40,
        58,
        "Logikality document pipeline — AWS architecture",
        size=32,
        weight="bold",
    )
    s.text(
        40,
        92,
        "Asynchronous ingest and processing, read left to right: ingest A–C, then worker steps 1–7. "
        "Failure handling, alerting, security and the production extension are shown separately.",
        size=18,
        color=MUTED,
    )
    s.text(
        40,
        122,
        "Repository state: the Terraform module is defined, validated and tested with a mocked "
        "provider but NOT applied — no resource is verified as deployed. API and worker code is "
        "implemented and tested locally (moto, LocalStack).",
        size=16,
        color=MUTED,
    )


def ingress(s: Svg) -> None:
    s.zone(30, 160, 810, 520, "INGRESS")

    s.node(
        290,
        205,
        340,
        200,
        "IAM role · api-task",
        [
            "s3:PutObject  incoming/*",
            "s3:ListBucket  bucket only (HeadBucket)",
            "sqs:SendMessage, GetQueueAttributes",
            "kms:Decrypt, GenerateDataKey via S3/SQS",
            "no document reads, no DynamoDB",
        ],
        accent="security",
        status=["TERRAFORM"],
    )
    s.node(
        40,
        500,
        122,
        100,
        "Originator",
        ["lender / client"],
        accent="people",
        status=["EXTERNAL"],
        title_size=16,
    )
    s.node(
        320,
        490,
        170,
        120,
        "ALB",
        ["Application Load", "Balancer · HTTPS", "health: /health"],
        proposed=True,
        status=["PROPOSED"],
    )
    s.node(
        570,
        450,
        240,
        200,
        "API service",
        [
            "FastAPI · POST /documents",
            "checks type, size ≤ 10 MiB,",
            "non-empty body",
            "PutObject, then SendMessage",
            "returns 202 + document_id;",
            "does not wait for processing",
        ],
        proposed=True,
        status=["ECS · PROPOSED", "CODE"],
    )

    s.edge([(162, 535), (320, 535)], "proposed")
    s.label(166, 525, "POST /documents", badge="A", color=PROPOSED, size=13)
    s.edge([(320, 570), (162, 570)], "proposed")
    s.text(
        176, 592, "202 + document_id", size=13, color=PROPOSED, weight="bold", halo=True
    )
    s.edge([(490, 550), (570, 550)], "proposed")
    s.text(
        530,
        540,
        "HTTP :8080",
        size=12.5,
        color=PROPOSED,
        weight="bold",
        anchor="middle",
        halo=True,
    )

    s.edge([(600, 405), (600, 450)], "iam")


def storage_and_queue(s: Svg) -> None:
    s.zone(860, 160, 460, 520, "DOCUMENT STORAGE & JOB QUEUE")

    s.node(
        880,
        200,
        410,
        225,
        "Amazon S3 · documents bucket",
        ["logikality-{env}-docs-{account_id} · versioned"],
        accent="storage",
        status=["TERRAFORM"],
        chips=["KMS CMK · bucket key", "Block Public Access", "TLS-only"],
    )
    for top, prefix, desc in (
        (262, "incoming/{document_id}", "original upload — API writes, worker reads"),
        (
            328,
            "processed/{document_id}.json",
            "result — worker writes · IA after 30 days",
        ),
    ):
        s.rect(896, top, 378, 56, fill="#f0fdf4", stroke="#86efac", width=1.2, rx=6)
        s.text(910, top + 23, prefix, size=14, weight="bold", layer=s.nodes)
        s.text(910, top + 43, desc, size=13, color=MUTED, layer=s.nodes)

    s.node(
        920,
        450,
        250,
        200,
        "Amazon SQS",
        [
            ("processing queue", BOLD),
            "visibility timeout 300 s",
            "long-poll wait 20 s · retention 4 d",
            "message = pointer only:",
            "document_id, s3_key, sha256",
        ],
        accent="integration",
        status=["TERRAFORM"],
        chips=["KMS CMK"],
    )

    # API -> S3 and API -> SQS
    s.edge([(780, 450), (780, 290), (880, 290)])
    s.label(788, 280, "PutObject", badge="B", size=13)
    s.edge([(810, 550), (920, 550)])
    s.label(814, 540, "SendMessage", badge="C", size=13)


def processing(s: Svg) -> None:
    s.zone(1340, 160, 930, 730, "PROCESSING — WORKER, IDEMPOTENCY, EXTERNAL DEPENDENCY")

    s.node(
        1560,
        205,
        240,
        130,
        "OCR / LLM provider",
        ["external dependency", "not in code — would plug", "into _process_document"],
        proposed=True,
        status=["PROPOSED"],
    )
    s.node(
        1840,
        205,
        410,
        200,
        "IAM role · worker-task",
        [
            "s3:GetObject incoming/* · PutObject processed/*",
            "sqs:ReceiveMessage, DeleteMessage,",
            "     ChangeMessageVisibility, GetQueueAttributes",
            "dynamodb:PutItem, UpdateItem, GetItem",
            "kms:Decrypt, GenerateDataKey via S3/SQS/DDB",
            "no sqs:SendMessage, no DLQ access",
        ],
        accent="security",
        status=["TERRAFORM"],
    )
    s.node(
        1460,
        450,
        260,
        200,
        "Worker service",
        [
            "python -m docproc.worker",
            "scales independently of API",
            "step 4 today: verify sha256,",
            "build result JSON (stub)",
            "SIGTERM: stop polling, drain",
        ],
        proposed=True,
        status=["ECS · PROPOSED", "CODE"],
    )
    s.node(
        2000,
        450,
        250,
        200,
        "Amazon DynamoDB",
        [
            ("idempotency table", BOLD),
            "pk = document_id",
            "status store — no documents",
            "TTL expires_at · PITR",
            "on-demand capacity",
        ],
        accent="database",
        status=["TERRAFORM"],
        chips=["KMS CMK"],
    )

    # 1, 7, retry: worker -> SQS
    s.edge([(1460, 490), (1170, 490)])
    s.label(1186, 480, "ReceiveMessage (long poll)", badge="1", size=13.5)
    s.edge([(1460, 560), (1170, 560)])
    s.label(1186, 550, "DeleteMessage", badge="7", size=13.5)
    s.text(
        1214, 580, "only after steps 5 and 6 succeed", size=13, color=MUTED, halo=True
    )
    s.edge([(1460, 625), (1170, 625)], "retry")
    s.text(
        1186,
        615,
        "retry: ChangeMessageVisibility",
        size=13.5,
        weight="bold",
        color="#b45309",
        halo=True,
    )

    # 2, 6: worker -> DynamoDB
    s.edge([(1720, 495), (2000, 495)])
    s.label(1730, 485, "PutItem (conditional claim)", badge="2", size=13.5)
    s.text(1758, 515, "attribute_not_exists(pk);", size=13, color=MUTED, halo=True)
    s.text(1758, 533, "on conflict GetItem → status", size=13, color=MUTED, halo=True)
    s.edge([(1720, 600), (2000, 600)])
    s.label(1730, 590, "UpdateItem COMPLETED", badge="6", size=13.5)

    # 3, 5: worker -> S3 (outer vertical takes the upper row, so no crossing)
    s.edge([(1510, 450), (1510, 290), (1290, 290)])
    s.label(1346, 280, "GetObject", badge="3", size=13.5)
    s.edge([(1480, 450), (1480, 356), (1290, 356)])
    s.label(1346, 346, "PutObject", badge="5", size=13.5)

    # 4: worker -> OCR/LLM (proposed)
    s.edge([(1650, 450), (1650, 335)], "proposed")
    s.label(1660, 396, "extract (proposed)", badge="4", color=PROPOSED, size=13.5)

    s.edge([(1900, 405), (1900, 428), (1700, 428), (1700, 450)], "iam")

    s.rect(1820, 676, 435, 204, fill="#ffffff", stroke="#a5b4fc", width=1.4)
    s.text(
        1836,
        700,
        "Idempotency semantics (DynamoDB)",
        size=15,
        weight="bold",
        layer=s.nodes,
    )
    s.lines(
        1836,
        722,
        [
            "• COMPLETED: duplicate delivery is deleted without",
            "   repeating the work (log: idempotency_skip).",
            "• IN_PROGRESS: not deleted; jittered back-off avoids",
            "   two workers processing one document at once.",
            "• SQS stays at-least-once. Duplicate business effects",
            "   are prevented — not exactly-once execution.",
            ("! Not implemented: lease expiry / conditional reclaim.", RED_BOLD),
            ("   A crash or error after step 2 leaves IN_PROGRESS, so", RED),
            ("   retries back off to the DLQ and redriven jobs stay", RED),
            ("   blocked until the 7-day TTL removes the claim.", RED),
        ],
        size=13,
        leading=16.2,
        layer=s.nodes,
    )


def failure_handling(s: Svg) -> None:
    s.zone(
        30,
        700,
        1290,
        490,
        "FAILURE HANDLING — RETRY, DEAD-LETTER QUEUE AND CONTROLLED REDRIVE",
    )

    s.rect(50, 745, 500, 425, fill="#fffbeb", stroke="#f59e0b", width=1.4)
    s.text(
        68,
        774,
        "Retry path — separate from the DLQ",
        size=16,
        weight="bold",
        color="#b45309",
        layer=s.nodes,
    )
    s.lines(
        68,
        800,
        [
            "Failed attempts are retried by SQS redelivery. The worker",
            "never deletes a failed message; it only changes visibility.",
            ("• Transient (throttling, 5xx, timeouts):", BOLD),
            "   visibility = random(1, min(900, 2^receiveCount)) s —",
            "   exponential back-off with full jitter",
            ("• Permanent (bad body, missing object, sha256", BOLD),
            ("   mismatch, non-retryable AWS error):", BOLD),
            "   visibility 5 s, so it uses up its receives quickly",
            ("• IN_PROGRESS claim found:", BOLD),
            "   same jittered back-off, message kept",
            "• Each redelivery increments ApproximateReceiveCount.",
            "   SQS moves a message to the DLQ only after more than",
            "   5 receives — one failure never goes straight there.",
            "• Alarm retry-ratio (received ÷ deleted > 2) flags",
            "   abnormal retry activity.",
        ],
        size=14,
        leading=21.5,
        layer=s.nodes,
    )

    s.node(
        920,
        920,
        250,
        160,
        "Amazon SQS · DLQ",
        ["processing-dlq · retention 14 d", "redrive-allow: processing", "queue only"],
        accent="integration",
        status=["TERRAFORM"],
        chips=["KMS CMK"],
    )
    s.node(
        600,
        960,
        240,
        130,
        "On-call operator",
        [
            "runbook §4.10 · Alert B",
            "inspect DLQ (no delete),",
            "fix cause, start move task",
        ],
        accent="people",
        status=["RUNBOOK"],
        title_size=16,
    )
    s.edge([(840, 1020), (920, 1020)], "control")
    s.lines(
        600,
        1118,
        [
            ("! No operator IAM role for", RED_BOLD),
            ("  sqs:StartMessageMoveTask in Terraform", RED),
        ],
        size=13,
        leading=18,
    )

    # Automatic DLQ move (down) and controlled redrive (up) on separate lines.
    s.edge([(960, 650), (960, 920)], "dlq")
    s.lines(
        948,
        760,
        [
            ("Automatic move to DLQ", {"weight": "bold", "color": "#dc2626"}),
            "SQS redrive policy, after",
            "more than maxReceiveCount = 5",
            "receives without DeleteMessage",
        ],
        size=14,
        leading=19,
        anchor="end",
        halo=True,
    )
    s.edge([(1110, 920), (1110, 650)], "redrive")
    s.lines(
        1122,
        742,
        [
            ("Controlled redrive", {"weight": "bold", "color": "#7c3aed"}),
            "manual, after the fix:",
            "StartMessageMoveTask",
            "DLQ → processing queue",
            "≤ 2 msg/s (runbook §4.10)",
        ],
        size=14,
        leading=19,
        halo=True,
    )


def monitoring(s: Svg) -> None:
    s.zone(
        1340,
        910,
        930,
        280,
        "MONITORING & ALERTING — OBSERVES THE PIPELINE, NOT IN THE PROCESSING PATH",
    )

    s.node(
        1360,
        950,
        460,
        225,
        "Amazon CloudWatch",
        [
            "Alarms in Terraform (alarm + OK actions → SNS):",
            ("• queue-oldest-message-age — SLO warning", BOLD),
            "   max > 900 s for 3 of 3 one-minute periods",
            ("• dlq-messages-visible", BOLD),
            "   DLQ visible messages > 0 within 5 minutes",
            ("• retry-ratio — abnormal retry activity", BOLD),
            "   received ÷ deleted > 2 for 3 × 5 minutes",
            ("Proposed: ECS task/CPU/memory alarms, log metrics", ORANGE),
        ],
        accent="management",
        status=["TERRAFORM"],
        body_size=13.5,
        leading=19,
    )
    s.node(
        1900,
        950,
        350,
        95,
        "Amazon SNS",
        ["alerts topic"],
        accent="integration",
        status=["TERRAFORM"],
        chips=["KMS CMK"],
    )
    s.node(
        1900,
        1080,
        350,
        95,
        "Alert destination",
        [
            "email only if alert_email is set (default: none)",
            ("paging (PagerDuty): proposed", ORANGE),
        ],
        accent="external",
        status=["TF · OPTIONAL"],
        title_size=16,
        body_size=13,
    )
    s.edge([(1820, 995), (1900, 995)])
    s.text(
        1860, 985, "alarm / OK", size=12.5, weight="bold", anchor="middle", halo=True
    )
    s.edge([(2075, 1045), (2075, 1080)])

    # Telemetry
    s.edge(
        [(1150, 650), (1150, 690), (1330, 690), (1330, 985), (1360, 985)], "telemetry"
    )
    s.text(
        1160,
        684,
        "AWS/SQS metrics (processing queue)",
        size=12.5,
        color="#0f766e",
        weight="bold",
        halo=True,
    )
    s.edge([(1170, 1040), (1360, 1040)], "telemetry")
    s.text(
        1180,
        1032,
        "AWS/SQS metrics (DLQ)",
        size=12.5,
        color="#0f766e",
        weight="bold",
        halo=True,
    )
    s.edge([(1530, 650), (1530, 950)], "telemetry")
    s.lines(
        1520,
        742,
        [
            ("worker JSON logs", {"weight": "bold", "color": "#0f766e"}),
            "duration_ms, error_type,",
            "receive_count, msg",
            ("shipping via ECS: proposed", ORANGE),
        ],
        size=13,
        leading=18,
        anchor="end",
        halo=True,
    )
    s.edge([(1660, 650), (1660, 950)], "telemetry")
    s.lines(
        1672,
        742,
        [
            ("ECS metrics", {"weight": "bold", "color": "#0f766e"}),
            ("(proposed): running", ORANGE),
            ("vs desired, CPU,", ORANGE),
            ("memory, stopped", ORANGE),
        ],
        size=13,
        leading=18,
        halo=True,
    )


def security(s: Svg) -> None:
    s.zone(
        30, 1210, 1290, 330, "SECURITY & ENCRYPTION — CONFIGURATION, NOT A RUNTIME STEP"
    )

    s.node(
        50,
        1255,
        340,
        265,
        "AWS KMS · customer-managed key",
        [
            "alias/logikality-{env}-pipeline",
            ("automatic key rotation: enabled", BOLD),
            "deletion window: 30 days",
            "key policy: account root; SQS, SNS",
            "and CloudWatch service principals",
            "",
            ("Rotation is key configuration —", {"italic": "1"}),
            ("not a step in the job flow.", {"italic": "1"}),
        ],
        accent="security",
        status=["TERRAFORM"],
        title_size=16,
    )
    s.text(
        415,
        1278,
        "Encrypted at rest with this CMK (verified in Terraform)",
        size=15,
        weight="bold",
    )
    s.lines(
        415,
        1302,
        [
            "• S3 documents bucket: default SSE-KMS + bucket key;",
            "   policy denies PutObject without this key",
            "• SQS processing queue and DLQ (300 s data-key reuse)",
            "• DynamoDB idempotency table · SNS alerts topic",
            (
                "Not this CMK: S3 access-log bucket (SSE-S3, needed for",
                {"color": FAINT},
            ),
            ("log delivery); ECR repository (AWS-managed key)", {"color": FAINT}),
            "Services fetch data keys transparently; task roles",
            "get only kms:ViaService-scoped Decrypt/GenerateDataKey.",
            "KMS CMK chips on the boxes above mark these resources.",
            ("! Uploads must send SSE-KMS with the key ARN (env", RED_BOLD),
            ("   KMS_KEY_ID); if unset, the bucket policy denies them", RED),
        ],
        size=14,
        leading=20,
    )
    s.text(870, 1278, "Least privilege & access boundaries", size=15, weight="bold")
    s.lines(
        870,
        1302,
        [
            "• Separate api-task / worker-task roles, assumable only",
            "   by ecs-tasks.amazonaws.com from this account",
            "• No s3:* — actions scoped to incoming/ or processed/",
            "• S3 Block Public Access (all 4) + BucketOwnerEnforced",
            "• Bucket and queue policies deny non-TLS requests",
            "• Optional permissions boundary on task roles",
            "• No secrets in the image or this diagram; tasks use",
            "   role credentials (Secrets Manager: proposed)",
            "• CI: GitHub OIDC role + ECR, optional module (off)",
        ],
        size=14,
        leading=21,
    )


def production_extension(s: Svg) -> None:
    s.zone(
        1340,
        1210,
        930,
        330,
        "PROPOSED PRODUCTION EXTENSION — NOT DEPLOYED (detail: docs/architecture-future.png)",
        proposed=True,
    )

    s.rect(
        1360,
        1250,
        590,
        275,
        fill="#ffffff",
        stroke=PROPOSED,
        width=1.4,
        dash="6 4",
        layer=s.zones,
    )
    s.text(1374, 1272, "VPC · 3 AZs", size=13, weight="bold", color=PROPOSED)
    cols = (
        (1372, 160, "Public subnets"),
        (1544, 200, "Private app subnets"),
        (1756, 182, "Private data subnets"),
    )
    for x, w, title in cols:
        s.rect(
            x,
            1282,
            w,
            232,
            fill="#fffaf5",
            stroke="#fdba74",
            width=1,
            rx=6,
            layer=s.zones,
        )
        s.text(
            x + w / 2,
            1302,
            title,
            size=12.5,
            weight="bold",
            color=MUTED,
            anchor="middle",
            layer=s.zones,
        )

    def mini(x: float, y: float, w: float, title: str, sub: str) -> None:
        s.rect(x, y, w, 64, fill="#ffffff", stroke=PROPOSED, width=1.6, dash="6 4")
        s.text(
            x + w / 2,
            y + 26,
            title,
            size=14,
            weight="bold",
            anchor="middle",
            layer=s.nodes,
        )
        s.text(
            x + w / 2,
            y + 46,
            sub,
            size=12.5,
            color=MUTED,
            anchor="middle",
            layer=s.nodes,
        )

    mini(1384, 1316, 136, "ALB", "HTTPS · WAF")
    mini(1384, 1430, 136, "NAT gateway", "egress only")
    mini(1560, 1316, 168, "ECS API tasks", "sg-app")
    mini(1560, 1430, 168, "ECS worker tasks", "sg-app · autoscaled")
    s.rect(1770, 1330, 154, 150, fill="#ffffff", stroke=PROPOSED, width=1.6, dash="6 4")
    s.lines(
        1847,
        1356,
        [
            ("RDS PostgreSQL", BOLD),
            "Multi-AZ, if needed",
            ("sg-rds inbound:", BOLD),
            "5432 from sg-app",
            "only",
        ],
        size=12.5,
        leading=19,
        anchor="middle",
        layer=s.nodes,
    )
    s.edge([(1520, 1348), (1560, 1348)], "proposed")
    s.edge([(1728, 1348), (1770, 1348)], "proposed")
    s.edge([(1728, 1462), (1770, 1462)], "proposed")
    s.text(
        1749,
        1340,
        "5432",
        size=11.5,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.text(
        1749,
        1454,
        "5432",
        size=11.5,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(1560, 1475), (1520, 1475)], "proposed")
    s.text(
        1540,
        1340,
        "8080",
        size=11.5,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )

    s.lines(
        1966,
        1268,
        [
            ("VPC endpoints", BOLD),
            "gateway: S3, DynamoDB",
            "interface: SQS, ECR, Logs, KMS,",
            "STS, Secrets Manager; NAT only",
            "for the OCR/LLM vendor",
            ("Worker autoscaling", BOLD),
            "backlog per task + oldest age;",
            "maxCapacity capped by OCR/LLM",
            "quota and DB connections",
            ("RDS only for relational data", BOLD),
            "(job metadata, audit). Documents",
            "stay in S3; idempotency in DynamoDB",
        ],
        size=13,
        leading=20.5,
    )


def legend(s: Svg) -> None:
    s.rect(
        30,
        1560,
        2240,
        150,
        fill="#ffffff",
        stroke=ZONE,
        width=1.4,
        rx=10,
        layer=s.zones,
    )
    s.text(48, 1588, "LEGEND", size=14, weight="bold", color=MUTED, spacing=0.8)

    x = 150
    for kind, text in (
        ("data", "Request / data flow (arrow: caller → callee)"),
        ("proposed", "Flow through a proposed component"),
        ("retry", "Retry: ChangeMessageVisibility"),
        ("dlq", "Automatic DLQ move (SQS redrive policy)"),
        ("redrive", "Controlled redrive DLQ → queue (manual)"),
    ):
        x = legend_swatch(s, x, 1584, kind, text)

    x = 150
    for kind, text in (
        ("telemetry", "Telemetry → CloudWatch"),
        ("iam", "IAM role assumed by task (permission)"),
        ("control", "Operator control action"),
    ):
        x = legend_swatch(s, x, 1630, kind, text)
    s.badge(x + 11, 1625, "A")
    s.badge(x + 37, 1625, "1")
    s.text(
        x + 58, 1630, "order: ingest A–C, then worker steps 1–7 (success path)", size=14
    )

    y = 1676
    x = 150
    s.rect(
        x,
        y - 14,
        44,
        28,
        fill="#ffffff",
        stroke="#3f8624",
        width=1.8,
        rx=5,
        layer=s.labels,
    )
    s.text(x + 54, y + 5, "Solid border: AWS resource defined in Terraform", size=14)
    x += 54 + 360
    s.rect(
        x,
        y - 14,
        44,
        28,
        fill="#fff7ed",
        stroke=PROPOSED,
        width=2,
        dash="6 4",
        rx=5,
        layer=s.labels,
    )
    s.text(x + 54, y + 5, "Dashed orange border: not deployed / proposed", size=14)
    x += 54 + 360
    for tag, text in (
        ("TERRAFORM", "defined + validated, not applied"),
        ("CODE", "implemented, tested locally"),
        ("PROPOSED", "design only"),
    ):
        x += s.pill(x, y, tag, anchor="start") + 8
        s.text(x, y + 5, text, size=14, color=MUTED)
        x += len(text) * 7.3 + 26
    x += s.pill(x, y, "KMS CMK", anchor="start", fg="#7c2d12", bg="#fef3c7") + 8
    s.text(x, y + 5, "encrypted with the pipeline key", size=14, color=MUTED)


ZONE = "#cbd5e1"


def main() -> None:
    s = Svg(2300, 1730)
    header(s)
    ingress(s)
    storage_and_queue(s)
    processing(s)
    failure_handling(s)
    monitoring(s)
    security(s)
    production_extension(s)
    legend(s)
    s.save(SVG_OUT, PNG_OUT)


if __name__ == "__main__":
    main()

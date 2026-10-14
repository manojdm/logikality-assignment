#!/usr/bin/env python3
"""Render docs/architecture-future.png: the proposed production extension.

Nothing in this view is applied. It follows docs/architecture-extension.md and
reuses the existing Terraform resources (S3, SQS + DLQ, DynamoDB, KMS, alarms).

    python docs/diagrams/architecture-future.py   # or: make diagram
"""

from __future__ import annotations

from pathlib import Path

from svgkit import INK, MUTED, PROPOSED, Svg, legend_swatch

ROOT = Path(__file__).resolve().parents[2]
SVG_OUT = Path(__file__).with_suffix(".svg")
PNG_OUT = ROOT / "docs" / "architecture-future.png"

BOLD = {"weight": "bold", "color": INK}
ORANGE = {"color": PROPOSED}


def main() -> None:
    s = Svg(2040, 1240)

    s.text(
        40,
        58,
        "Logikality — proposed production extension (not deployed)",
        size=32,
        weight="bold",
    )
    s.text(
        40,
        92,
        "How application compute, a relational database and production networking would wrap the "
        "existing Terraform resources. Design only: nothing in this view is applied.",
        size=18,
        color=MUTED,
    )
    s.text(
        40,
        120,
        "Source: docs/architecture-extension.md. The current-state diagram is architecture.png; "
        "today the app uses S3 for documents and DynamoDB for idempotency, not RDS.",
        size=16,
        color=MUTED,
    )

    # External actors
    s.zone(30, 160, 200, 860, "EXTERNAL")
    s.node(
        45,
        330,
        170,
        100,
        "Originator",
        ["lender / client"],
        accent="people",
        status=["EXTERNAL"],
        title_size=16,
    )
    s.node(
        45,
        760,
        170,
        120,
        "OCR / LLM",
        ["vendor API", "(HTTPS egress)"],
        proposed=True,
        status=["PROPOSED"],
        title_size=16,
    )

    # VPC
    s.zone(250, 160, 1250, 860, "VPC · 3 AVAILABILITY ZONES — PROPOSED", proposed=True)
    columns = (
        (270, 260, "PUBLIC SUBNETS"),
        (550, 420, "PRIVATE APP SUBNETS"),
        (990, 290, "PRIVATE DATA SUBNETS (no internet route)"),
        (1300, 180, "VPC ENDPOINTS"),
    )
    for x, w, title in columns:
        s.rect(
            x,
            200,
            w,
            800,
            fill="#fffaf5",
            stroke="#fdba74",
            width=1.2,
            rx=8,
            layer=s.zones,
        )
        s.text(
            x + 14,
            224,
            title,
            size=12.5,
            weight="bold",
            color=MUTED,
            layer=s.zones,
            spacing=0.6,
        )

    s.node(
        290,
        310,
        220,
        140,
        "ALB",
        ["HTTPS (ACM certificate)", "AWS WAF managed rules", "+ rate limit · sg-alb"],
        proposed=True,
        status=["PROPOSED"],
    )
    s.node(
        290,
        750,
        220,
        140,
        "NAT gateway",
        ["one per AZ in prod", "egress only, used for", "the OCR/LLM vendor"],
        proposed=True,
        status=["PROPOSED"],
    )
    s.node(
        580,
        270,
        360,
        220,
        "ECS service · API",
        [
            "Fargate on-demand · sg-api",
            "task role: api-task (exists in Terraform)",
            "target tracking: CPU 70 %, request count",
            "circuit breaker + rollback",
            "health check /health, smoke /ready",
            "secrets injected from Secrets Manager",
        ],
        proposed=True,
        status=["PROPOSED", "CODE"],
    )
    s.node(
        580,
        640,
        360,
        250,
        "ECS service · worker",
        [
            "Fargate Spot (work is idempotent) · sg-worker",
            "task role: worker-task (exists in Terraform)",
            ("autoscaling", BOLD),
            "target: visible messages per running task",
            "(~5) plus an oldest-message-age guard",
            "maxCapacity bounded by OCR/LLM quota",
            "and RDS Proxy connections",
            "SIGTERM: stop polling, finish batch",
        ],
        proposed=True,
        status=["PROPOSED", "CODE"],
    )
    s.node(
        1020,
        360,
        230,
        110,
        "RDS Proxy",
        ["connection pooling", "sg-rds-proxy"],
        proposed=True,
        status=["PROPOSED"],
    )
    s.node(
        1020,
        560,
        230,
        200,
        "RDS PostgreSQL",
        [
            "Multi-AZ, if relational",
            "data is required",
            "job metadata, audit trail",
            "encrypted with the CMK",
            "force_ssl · PITR · backups",
        ],
        proposed=True,
        status=["PROPOSED"],
    )
    s.node(
        1315,
        270,
        150,
        640,
        "Endpoints",
        [
            ("Gateway", BOLD),
            "S3",
            "DynamoDB",
            "",
            ("Interface", BOLD),
            "SQS",
            "ECR api",
            "ECR dkr",
            "CloudWatch",
            "  Logs",
            "KMS",
            "STS",
            "Secrets",
            "  Manager",
            "",
            "AWS API calls",
            "stay off the",
            "internet; cuts",
            "NAT cost",
        ],
        proposed=True,
        status=["PROPOSED"],
        title_size=16,
        leading=20.5,
    )

    # Regional services (existing Terraform)
    s.zone(1520, 160, 490, 860, "REGIONAL AWS SERVICES")
    services = (
        ("Amazon S3", "documents: incoming/, processed/", "storage", ["TERRAFORM"]),
        ("Amazon SQS", "processing queue + DLQ", "integration", ["TERRAFORM"]),
        ("Amazon DynamoDB", "idempotency / status table", "database", ["TERRAFORM"]),
        ("AWS KMS", "pipeline CMK, rotation enabled", "security", ["TERRAFORM"]),
        ("CloudWatch + SNS", "3 alarms → alerts topic", "management", ["TERRAFORM"]),
        (
            "Amazon ECR",
            "image registry (optional module)",
            "compute",
            ["TF · OPTIONAL"],
        ),
        (
            "Secrets Manager",
            "DB credentials, vendor API keys",
            "security",
            ["PROPOSED"],
        ),
    )
    y = 200
    for title, sub, accent, status in services:
        s.node(
            1540,
            y,
            450,
            96,
            title,
            [sub],
            accent=accent,
            status=status,
            proposed=status == ["PROPOSED"],
        )
        y += 112

    # Flows
    s.edge([(215, 380), (290, 380)], "proposed")
    s.text(
        252,
        370,
        "HTTPS",
        size=13,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(510, 380), (580, 380)], "proposed")
    s.text(
        545,
        370,
        ":8080",
        size=13,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )

    s.edge([(940, 410), (1020, 410)], "proposed")
    s.text(
        980,
        400,
        "5432",
        size=13,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(940, 690), (980, 690), (980, 445), (1020, 445)], "proposed")
    s.text(
        1000,
        520,
        "5432",
        size=13,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(1135, 470), (1135, 560)], "proposed")

    s.edge([(940, 300), (1315, 300)], "proposed")
    s.text(
        1128,
        290,
        "S3 / SQS API calls via endpoints",
        size=13,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(940, 860), (1315, 860)], "proposed")
    s.text(
        1128,
        850,
        "S3 / SQS / DynamoDB via endpoints",
        size=13,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(1465, 590), (1540, 590)], "proposed")
    s.text(
        1502,
        580,
        "private",
        size=12.5,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )

    s.edge([(580, 820), (510, 820)], "proposed")
    s.text(
        545,
        810,
        "egress",
        size=12.5,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )
    s.edge([(290, 820), (215, 820)], "proposed")
    s.text(
        252,
        810,
        "HTTPS",
        size=12.5,
        weight="bold",
        color=PROPOSED,
        anchor="middle",
        halo=True,
    )

    # Security-group rules
    s.rect(
        30,
        1040,
        1470,
        112,
        fill="#ffffff",
        stroke="#cbd5e1",
        width=1.4,
        rx=10,
        layer=s.zones,
    )
    s.text(
        48,
        1066,
        "SECURITY-GROUP RULES (PROPOSED)",
        size=14,
        weight="bold",
        color=MUTED,
        spacing=0.8,
    )
    s.lines(
        48,
        1092,
        [
            "sg-alb: 443 from the internet (via WAF) · sg-api: 8080 from sg-alb only · "
            "sg-worker: no inbound",
            "sg-rds-proxy / sg-rds: PostgreSQL 5432 only from the authorised app task security "
            "groups (sg-api, sg-worker); data subnets have no route to the internet",
            "Endpoint SGs: 443 from sg-api and sg-worker · VPC Flow Logs to the log bucket",
        ],
        size=14.5,
        leading=21,
        color=INK,
    )

    s.rect(
        1520,
        1040,
        490,
        112,
        fill="#ffffff",
        stroke="#cbd5e1",
        width=1.4,
        rx=10,
        layer=s.zones,
    )
    s.text(1538, 1066, "LEGEND", size=14, weight="bold", color=MUTED, spacing=0.8)
    legend_swatch(s, 1538, 1094, "proposed", "Proposed request / data flow")
    s.rect(
        1538,
        1112,
        44,
        26,
        fill="#fff7ed",
        stroke=PROPOSED,
        width=2,
        dash="6 4",
        rx=5,
        layer=s.labels,
    )
    s.text(1592, 1130, "Proposed — not deployed", size=14)
    s.rect(
        1800,
        1112,
        44,
        26,
        fill="#ffffff",
        stroke="#3f8624",
        width=1.8,
        rx=5,
        layer=s.labels,
    )
    s.text(1854, 1130, "In Terraform", size=14)

    s.text(
        40,
        1200,
        "The detailed current-state flow (claims, retries, DLQ, redrive, alarms) is "
        "in architecture.png. Rotation, IAM and encryption settings are unchanged by this "
        "extension.",
        size=14,
        color=MUTED,
        layer=s.labels,
    )

    s.save(SVG_OUT, PNG_OUT)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render architecture.png at the repository root."""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate
from diagrams.aws.integration import SNS, SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import ELB
from diagrams.aws.security import IAMRole, KMS
from diagrams.aws.database import Dynamodb
from diagrams.aws.storage import S3
from diagrams.onprem.client import Users

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "architecture"


def main() -> None:
    graph_attr = {"fontsize": "12", "bgcolor": "white", "pad": "0.4"}
    with Diagram(
        "Logikality document pipeline (current IaC + intended compute)",
        filename=str(OUT),
        outformat="png",
        show=False,
        graph_attr=graph_attr,
        direction="LR",
    ):
        users = Users("originator")
        with Cluster("Intended compute (documented, not applied)"):
            alb = ELB("ALB")
            api = Fargate("API task")
            worker = Fargate("Worker task")
        with Cluster("Terraform module document-pipeline"):
            kms = KMS("CMK\nrotation on")
            bucket = S3("documents\nincoming/ processed/")
            queue = SQS("processing\nlong-poll 20s")
            dlq = SQS("DLQ\nmaxReceive=5")
            table = Dynamodb("idempotency")
            alarms = Cloudwatch("age + DLQ +\nretry-ratio")
            sns = SNS("alerts")
            api_role = IAMRole("api-task")
            worker_role = IAMRole("worker-task")

        users >> alb >> api
        api >> Edge(label="PutObject SSE-KMS") >> bucket
        api >> Edge(label="SendMessage") >> queue
        queue >> Edge(label="long-poll") >> worker
        worker >> Edge(label="Get/Put") >> bucket
        worker >> Edge(label="conditional PutItem") >> table
        queue >> Edge(label="redrive") >> dlq
        queue >> alarms
        dlq >> alarms
        alarms >> sns
        kms >> Edge(style="dashed") >> bucket
        kms >> Edge(style="dashed") >> queue
        kms >> Edge(style="dashed") >> table
        kms >> Edge(style="dashed") >> sns
        api_role >> api
        worker_role >> worker


if __name__ == "__main__":
    main()

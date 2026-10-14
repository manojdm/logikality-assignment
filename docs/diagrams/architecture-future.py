#!/usr/bin/env python3
"""Render the production-target architecture."""

from __future__ import annotations

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate
from diagrams.aws.database import RDS, Dynamodb, ElasticacheForRedis
from diagrams.aws.integration import SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import ALB, Endpoint, NATGateway, PrivateSubnet, PublicSubnet
from diagrams.aws.security import Cognito, KMS, SecretsManager, WAF
from diagrams.aws.storage import S3
from diagrams.onprem.client import Users

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "architecture-future"


def main() -> None:
    with Diagram(
        "Logikality production target",
        filename=str(OUT),
        outformat="png",
        show=False,
        graph_attr={"fontsize": "11", "bgcolor": "white"},
        direction="TB",
    ):
        users = Users("originators")
        cognito = Cognito("JWT / Cognito")
        waf = WAF("WAF + ACM")
        with Cluster("VPC /16 across 3 AZs"):
            with Cluster("public"):
                PublicSubnet("public")
                alb = ALB("ALB")
                nat = NATGateway("NAT")
            with Cluster("private app"):
                PrivateSubnet("app")
                api = Fargate("API on-demand")
                worker = Fargate("worker Spot")
            with Cluster("private data"):
                PrivateSubnet("data")
                rds = RDS("Postgres Multi-AZ\n+ RDS Proxy")
                redis = ElasticacheForRedis("optional cache")
            endpoints = Endpoint("VPCE\nS3 SQS DDB ECR Logs KMS STS")
        bucket = S3("documents")
        queue = SQS("processing + DLQ")
        table = Dynamodb("idempotency")
        secrets = SecretsManager("DB + API keys")
        kms = KMS("CMKs")
        cw = Cloudwatch("metrics logs traces")

        users >> cognito >> waf >> alb >> api
        alb >> api
        api >> queue
        api >> bucket
        queue >> worker
        worker >> bucket
        worker >> table
        api >> rds
        worker >> rds
        worker >> redis
        nat >> Edge(style="dashed", label="egress only") >> worker
        endpoints >> Edge(style="dashed") >> bucket
        secrets >> api
        kms >> bucket
        cw >> api
        cw >> worker


if __name__ == "__main__":
    main()

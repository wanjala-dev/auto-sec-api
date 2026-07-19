"""Ingest proof: assume the customer AutoSecAuditRole and read shipped logs.

End-to-end path: connection → sts:AssumeRole(ExternalId) → s3:ListObjects on
the customer's logs/ prefix → GetObject → gunzip → parse JSON records.
Prints counts + per-service breakdown. The full Celery worker (checkpoints,
dedupe, detections) builds on exactly this path.
"""

from __future__ import annotations

import gzip
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Assume the customer role and parse the newest shipped log batch."

    def add_arguments(self, parser):
        parser.add_argument("--connection", required=True)

    def handle(self, *args, **options):
        import boto3

        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        conn = AwsOrganizationConnection.objects.get(id=options["connection"])
        creds = boto3.client("sts").assume_role(
            RoleArn=f"arn:aws:iam::{conn.management_account_id}:role/{conn.role_name}",
            RoleSessionName="autosec-ingest",
            ExternalId=conn.external_id,
        )["Credentials"]
        s3 = boto3.client(
            "s3",
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
        objs = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=conn.trail_s3_bucket, Prefix=conn.trail_s3_prefix or "logs/"):
            objs.extend(page.get("Contents", []))
        self.stdout.write(f"OBJECTS: {len(objs)} under {conn.trail_s3_prefix}")
        if not objs:
            return
        newest = max(objs, key=lambda o: o["LastModified"])
        body = s3.get_object(Bucket=conn.trail_s3_bucket, Key=newest["Key"])["Body"].read()
        text = gzip.decompress(body).decode("utf-8", "replace")
        services: dict[str, int] = {}
        parsed = 0
        for line in text.splitlines():
            try:
                rec = json.loads(line)
                parsed += 1
                svc = (rec.get("attrs") or {}).get("com.docker.compose.service", "?")
                services[svc] = services.get(svc, 0) + 1
            except ValueError:
                continue
        self.stdout.write(f"NEWEST: {newest['Key']} ({newest['Size']}B)")
        self.stdout.write(f"RECORDS: {parsed} | SERVICES: {services}")

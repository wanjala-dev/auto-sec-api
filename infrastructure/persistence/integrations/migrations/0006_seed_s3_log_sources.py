"""Seed a first-class WorkspaceLogSource(kind=s3) from each connection's trail
config (ADR 0008 D7).

This is the migration that structurally ends the "logs silently stopped"
regression: the S3 read location moves off ``AwsOrganizationConnection.trail_s3_*``
(a field an unrelated re-verify could blank) into an owned WorkspaceLogSource row.
Idempotent + reversible; runs once per env with an existing trail bucket.
"""

from __future__ import annotations

from django.db import migrations


def seed_s3_log_sources(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Conn = apps.get_model("integrations", "AwsOrganizationConnection")
    LogSource = apps.get_model("integrations", "WorkspaceLogSource")

    for conn in Conn.objects.using(db_alias).exclude(trail_s3_bucket="").iterator(chunk_size=500):
        config = {
            "aws_connection_id": str(conn.id),
            "bucket": conn.trail_s3_bucket,
            "prefix": conn.trail_s3_prefix or "logs/",
        }
        existing = LogSource.objects.using(db_alias).filter(
            workspace_id=conn.workspace_id,
            kind="s3",
            config__aws_connection_id=str(conn.id),
        ).first()
        if existing is not None:
            # Keep bucket/prefix in sync; promote a draft to active. Never clobber
            # an operator-renamed source or a deliberately disabled one.
            existing.config = config
            if existing.status == "draft":
                existing.status = "active"
            existing.save(update_fields=["config", "status", "updated_at"])
            continue
        LogSource.objects.using(db_alias).create(
            workspace_id=conn.workspace_id,
            kind="s3",
            name="AWS S3 trail",
            config=config,
            status="active",
        )


def unseed(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    # Reverse: drop only the rows this migration would have created.
    LogSource = apps.get_model("integrations", "WorkspaceLogSource")
    LogSource.objects.using(db_alias).filter(kind="s3", name="AWS S3 trail").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0005_workspacelogsource"),
    ]

    operations = [
        migrations.RunPython(seed_s3_log_sources, unseed),
    ]

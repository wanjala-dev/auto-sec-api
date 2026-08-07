"""Integration tests for WorkspaceLogSource resolution + the seed migration
(ADR 0008 Phase 2).

The point of the phase: the S3 read *location* lives on an owned WorkspaceLogSource
row, not on the AWS connection — so a connection re-verify (the "logs silently
stopped" regression) can no longer blank where logs are read from.
"""

from __future__ import annotations

import importlib
from unittest import mock

import pytest

from components.integrations.application.log_ingest_service import read_source_windows
from components.integrations.application.ports.log_source_port import LogSourcePort, LogWindow
from components.integrations.application.providers.log_source_provider import LogSourceProvider

_PROVIDER_MODULE = "components.integrations.application.providers.log_source_provider"


class _RecordingAdapter(LogSourcePort):
    """A LogSourcePort stand-in that records every read's config + cursor."""

    def __init__(self):
        self.calls: list[tuple[dict, str]] = []

    def read_window(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow:
        self.calls.append((config, since))
        return LogWindow(records=(), cursor="", objects_scanned=0)


def _read_s3_config(connection):
    """Drive the real read seam (repo lookup + registry resolution + config
    assembly) with a recording S3 adapter; return the config the adapter saw."""
    adapter = _RecordingAdapter()
    provider = LogSourceProvider(sources={"s3": adapter})
    with mock.patch(f"{_PROVIDER_MODULE}.get_log_source_provider", return_value=provider):
        read_source_windows(connection)
    assert len(adapter.calls) == 1
    return adapter.calls[0][0]


@pytest.fixture
def connection(workspace_factory):
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    ws = workspace_factory()
    return AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="123456789012",
        role_name="AutoSecAuditRole",
        external_id=f"ext-{ws.id}",
        trail_s3_bucket="connection-bucket",
        trail_s3_prefix="logs/",
        status="connected",
    )


def _make_source(connection, *, bucket, prefix="logs/", status="active"):
    from infrastructure.persistence.integrations.models import WorkspaceLogSource

    return WorkspaceLogSource.objects.create(
        workspace_id=connection.workspace_id,
        kind="s3",
        name="AWS S3 trail",
        config={"aws_connection_id": str(connection.id), "bucket": bucket, "prefix": prefix},
        status=status,
    )


@pytest.mark.django_db
class TestS3ConfigResolution:
    def test_prefers_workspace_log_source_over_connection_trail(self, connection):
        source = _make_source(connection, bucket="source-bucket")
        cfg = _read_s3_config(connection)
        assert cfg["bucket"] == "source-bucket"
        assert cfg["source_id"] == str(source.id)
        # Credentials still come from the connection (the S3 source only owns location).
        assert cfg["management_account_id"] == "123456789012"
        assert cfg["external_id"] == connection.external_id

    def test_falls_back_to_connection_trail_when_no_source(self, connection):
        cfg = _read_s3_config(connection)
        assert cfg["bucket"] == "connection-bucket"
        assert cfg["source_id"] == ""

    def test_wiped_connection_trail_still_reads_via_log_source(self, connection):
        # The regression proof: blank the connection's trail field — the owned
        # WorkspaceLogSource still carries the location, so logs keep flowing.
        _make_source(connection, bucket="durable-bucket")
        connection.trail_s3_bucket = ""
        connection.trail_s3_prefix = ""
        connection.save(update_fields=["trail_s3_bucket", "trail_s3_prefix"])

        cfg = _read_s3_config(connection)
        assert cfg["bucket"] == "durable-bucket"

    def test_disabled_source_is_ignored_and_falls_back(self, connection):
        _make_source(connection, bucket="disabled-bucket", status="disabled")
        cfg = _read_s3_config(connection)
        assert cfg["bucket"] == "connection-bucket"

    def test_oldest_active_s3_source_wins_while_the_checkpoint_bridge_holds(self, connection):
        # Two active S3 rows share ONE per-connection IngestCheckpoint cursor —
        # until the S3 cursor migrates onto the per-source field, only the oldest
        # is read (the pre-multi-source behavior, kept deliberately).
        oldest = _make_source(connection, bucket="oldest-bucket")
        _make_source(connection, bucket="newest-bucket")
        cfg = _read_s3_config(connection)
        assert cfg["bucket"] == "oldest-bucket"
        assert cfg["source_id"] == str(oldest.id)


@pytest.mark.django_db
class TestSeedMigration:
    def _seed_fn(self):
        module = importlib.import_module("infrastructure.persistence.integrations.migrations.0006_seed_s3_log_sources")
        return module.seed_s3_log_sources

    def test_seed_creates_active_s3_source_idempotently(self, connection):
        import django.apps

        from infrastructure.persistence.integrations.models import WorkspaceLogSource

        seed = self._seed_fn()
        seed(django.apps.apps, None)
        seed(django.apps.apps, None)  # second run must not duplicate

        rows = WorkspaceLogSource.objects.filter(workspace_id=connection.workspace_id, kind="s3")
        assert rows.count() == 1
        row = rows.first()
        assert row.status == "active"
        assert row.config["bucket"] == "connection-bucket"
        assert row.config["prefix"] == "logs/"
        assert row.config["aws_connection_id"] == str(connection.id)

    def test_seed_skips_connections_without_a_trail_bucket(self, workspace_factory):
        import django.apps

        from infrastructure.persistence.integrations.models import (
            AwsOrganizationConnection,
            WorkspaceLogSource,
        )

        ws = workspace_factory()
        AwsOrganizationConnection.objects.create(
            workspace=ws,
            management_account_id="210987654321",
            role_name="AutoSecAuditRole",
            external_id=f"ext-{ws.id}",
            trail_s3_bucket="",  # never configured
            status="connected",
        )
        self._seed_fn()(django.apps.apps, None)
        assert not WorkspaceLogSource.objects.filter(workspace_id=ws.id).exists()

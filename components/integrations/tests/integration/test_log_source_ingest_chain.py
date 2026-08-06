"""Log-source ENDPOINT → INGEST chain (ADR 0008) — the backbone leg after CRUD.

``test_log_source_api.py`` covers create/verify/patch/delete in isolation; this
suite chains them into the walk a customer actually takes and proves the tick
that matters afterwards:

    POST  …/log-sources/            create the S3 source (draft)
    POST  …/log-sources/<id>/verify/  adapter stubbed → ACTIVE, listed as such
    ingest tick (``scan_workspace_for_errors``) — the LogSourcePort read:
        * the adapter receives the SOURCE row's bucket/prefix (the ADR 0008 D7
          fix — a connection re-verify can no longer blank where logs are read
          from),
        * an ERROR record becomes an evidence-bearing ``ErrorFinding``,
        * the ``IngestCheckpoint`` cursor advances, and the next tick resumes
          AFTER it (idempotent — no double-alerting).

CloudWatch gets the same endpoint chain (create → verify → ACTIVE via the
CloudWatch adapter). NOTE the pinned gap: the ingest READ path
(``log_ingest_service.read_source_window``) still resolves only the "s3"
adapter — an ACTIVE CloudWatch source verifies but is never read by the error
scan. Named in the suite so the ADR 0008 phase that wires it has its landing
spot; do not fake it here.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.log_ingest_service import LogRecord, scan_workspace_for_errors
from components.integrations.application.ports.log_source_port import LogSourceHealth, LogWindow

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_S3_ADAPTER = "components.integrations.infrastructure.adapters.log_sources.s3_log_source_adapter.S3LogSourceAdapter"
_CW_ADAPTER = (
    "components.integrations.infrastructure.adapters.log_sources."
    "cloudwatch_log_source_adapter.CloudWatchLogSourceAdapter"
)


def _base(workspace_id) -> str:
    return f"/integrations/workspaces/{workspace_id}/log-sources/"


@pytest.fixture
def owner_ws(workspace_factory):
    ws = workspace_factory()
    return ws, ws.workspace_owner


class _RecordingS3Reader:
    """Stands in for ``S3LogSourceAdapter.read_window`` — records the config +
    cursor of every call and serves scripted windows."""

    def __init__(self, windows: list[LogWindow]):
        self.windows = list(windows)
        self.calls: list[tuple[dict, str]] = []

    def __call__(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow:
        self.calls.append((config, since))
        if self.windows:
            return self.windows.pop(0)
        return LogWindow(records=(), cursor=since, objects_scanned=0)


def _error_window() -> LogWindow:
    records = (
        LogRecord(service="api", level="INFO", raw="INFO healthy", message="healthy"),
        LogRecord(
            service="celery_worker",
            level="ERROR",
            raw="ERROR ImportError: cannot import name 'run_due_schedules'",
            message="ImportError: cannot import name 'run_due_schedules'",
        ),
    )
    return LogWindow(records=records, cursor="logs/2026/08/05/batch-002.gz", objects_scanned=2)


class TestS3SourceEndpointToIngestChain:
    def _activate_source(self, api_client, ws, owner, conn):
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {
                "kind": "s3",
                "name": "prod trail",
                "config": {"aws_connection_id": str(conn.id), "bucket": "acme-logs", "prefix": "logs/"},
            },
            format="json",
        )
        assert created.status_code == 201, created.data
        source = created.data["data"]
        assert source["status"] == "draft"

        with mock.patch(f"{_S3_ADAPTER}.verify", return_value=LogSourceHealth(ok=True)):
            verified = api_client.post(f"{_base(ws.id)}{source['id']}/verify/", {}, format="json")
        assert verified.status_code == 200, verified.data
        assert verified.data["data"]["status"] == "active"

        listed = api_client.get(_base(ws.id))
        assert [row["status"] for row in listed.data["data"]] == ["active"]
        return source

    def test_create_verify_then_ingest_tick_detects_errors(self, api_client, owner_ws, aws_connection_factory):
        ws, owner = owner_ws
        conn = aws_connection_factory(ws)
        source = self._activate_source(api_client, ws, owner, conn)

        reader = _RecordingS3Reader([_error_window()])
        with mock.patch(f"{_S3_ADAPTER}.read_window", new=reader):
            findings = scan_workspace_for_errors(ws.id)

        # The detection: one evidence-bearing finding from the ERROR line.
        assert len(findings) == 1
        finding = findings[0]
        assert finding.service == "celery_worker"
        assert finding.severity == "high"
        assert finding.signal == "ERROR in celery_worker"
        assert any(e["type"] == "log_line" for e in finding.evidence)
        assert finding.blast_radius["window_records"] == 2

        # ADR 0008 D7: the adapter read THE SOURCE ROW's location (+ identity
        # from the connection) — not the deprecated trail_s3_* fields.
        config, since = reader.calls[0]
        assert since == ""
        assert config["bucket"] == "acme-logs"
        assert config["prefix"] == "logs/"
        assert config["source_id"] == source["id"]
        assert config["management_account_id"] == conn.management_account_id
        assert config["external_id"] == conn.external_id

        # The cursor advanced past the processed window.
        from infrastructure.persistence.integrations.models import IngestCheckpoint

        checkpoint = IngestCheckpoint.objects.get(connection=conn, channel=IngestCheckpoint.Channel.S3_LIST)
        assert checkpoint.last_object_key == "logs/2026/08/05/batch-002.gz"
        assert checkpoint.objects_processed == 2

    def test_second_tick_resumes_after_the_cursor_and_stays_silent(self, api_client, owner_ws, aws_connection_factory):
        ws, owner = owner_ws
        conn = aws_connection_factory(ws)
        self._activate_source(api_client, ws, owner, conn)

        reader = _RecordingS3Reader([_error_window()])  # second call → empty window
        with mock.patch(f"{_S3_ADAPTER}.read_window", new=reader):
            first = scan_workspace_for_errors(ws.id)
            second = scan_workspace_for_errors(ws.id)

        assert len(first) == 1
        assert second == [], "a re-run re-alerted on an already-processed window"
        # The second read started AFTER the first run's cursor (idempotency).
        assert reader.calls[1][1] == "logs/2026/08/05/batch-002.gz"

    def test_workspace_without_a_connected_source_detects_nothing(self, owner_ws):
        ws, _owner = owner_ws
        assert scan_workspace_for_errors(ws.id) == []


class TestCloudWatchSourceEndpointChain:
    def test_create_verify_marks_active(self, api_client, owner_ws, aws_connection_factory):
        ws, owner = owner_ws
        conn = aws_connection_factory(ws)
        api_client.force_authenticate(owner)

        created = api_client.post(
            _base(ws.id),
            {
                "kind": "cloudwatch",
                "name": "lambda logs",
                "config": {
                    "aws_connection_id": str(conn.id),
                    "log_group": "/aws/lambda/acme",
                    "region": "us-east-1",
                },
            },
            format="json",
        )
        assert created.status_code == 201, created.data
        source = created.data["data"]

        with mock.patch(f"{_CW_ADAPTER}.verify", return_value=LogSourceHealth(ok=True)) as patched:
            verified = api_client.post(f"{_base(ws.id)}{source['id']}/verify/", {}, format="json")

        assert verified.status_code == 200, verified.data
        assert verified.data["data"]["status"] == "active"
        assert verified.data["data"]["last_verified_at"] is not None
        # The CloudWatch adapter (not S3) served the probe, with the source's config.
        config = patched.call_args.args[0]
        assert config["log_group"] == "/aws/lambda/acme"
        assert config["region"] == "us-east-1"

    def test_verify_failure_marks_error_with_reason(self, api_client, owner_ws, aws_connection_factory):
        ws, owner = owner_ws
        conn = aws_connection_factory(ws)
        api_client.force_authenticate(owner)
        source = api_client.post(
            _base(ws.id),
            {
                "kind": "cloudwatch",
                "config": {"aws_connection_id": str(conn.id), "log_group": "/aws/lambda/acme"},
            },
            format="json",
        ).data["data"]

        with mock.patch(
            f"{_CW_ADAPTER}.verify",
            return_value=LogSourceHealth(ok=False, detail="AccessDeniedException"),
        ):
            verified = api_client.post(f"{_base(ws.id)}{source['id']}/verify/", {}, format="json")

        assert verified.data["data"]["status"] == "error"
        assert "AccessDeniedException" in verified.data["data"]["last_error"]

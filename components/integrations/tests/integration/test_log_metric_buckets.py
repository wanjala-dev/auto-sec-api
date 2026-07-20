"""Integration tests for the hourly security-metric buckets.

Real DB for the ``LogMetricBucket`` upserts; the S3 read stubbed at the
``iter_window_records`` boundary — no AWS. Proves:

* aggregation upserts are idempotent-additive: same (metric, service, source,
  hour) increments ONE row; a different hour creates a new row;
* ``query_metric`` group_bys (service / source / day / hour) and the window
  filter return the exact deterministic counts;
* ``top_sources`` ranks derived IPs and excludes blank sources;
* the ingest wiring is failure-safe — an aggregation error never breaks
  ``scan_connection`` or checkpoint advancement;
* the model's Metric choices stay in lockstep with the application taxonomy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from components.integrations.application.log_ingest_service import LogRecord
from components.integrations.application.log_metrics_service import (
    SECURITY_METRICS,
    aggregate_security_metrics,
)

_INGEST = "components.integrations.application.log_ingest_service"
_METRICS = "components.integrations.application.log_metrics_service"

_HOUR = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)


def _auth_line(ip="203.0.113.9", ts=_HOUR, service="web"):
    msg = f"Failed password for invalid user admin from {ip} port 51122 ssh2"
    return LogRecord(service=service, level="INFO", message=msg, raw=msg, ts=ts)


def _error_line(ts=_HOUR, service="celery"):
    msg = "unhandled exception in task"
    return LogRecord(service=service, level="ERROR", message=msg, raw=msg, ts=ts)


@pytest.fixture
def connection(workspace_factory):
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    workspace = workspace_factory()
    return AwsOrganizationConnection.objects.create(
        workspace=workspace,
        management_account_id="123456789012",
        role_name="AutoSecAuditRole",
        external_id=f"ext-{workspace.id}",
        trail_s3_bucket="acme-logs",
        status="connected",
    )


@pytest.mark.django_db
class TestAggregationUpsert:
    def test_same_hour_increments_single_row(self, connection):
        from infrastructure.persistence.integrations.models import LogMetricBucket

        aggregate_security_metrics(connection, [_auth_line(), _auth_line()])
        aggregate_security_metrics(connection, [_auth_line()])

        row = LogMetricBucket.objects.get(connection=connection, metric="auth_failure", source="203.0.113.9")
        assert row.count == 3
        assert row.bucket_start == _HOUR
        assert row.workspace_id == connection.workspace_id
        assert row.sample_message.startswith("Failed password")

    def test_different_hour_creates_new_row(self, connection):
        from infrastructure.persistence.integrations.models import LogMetricBucket

        aggregate_security_metrics(connection, [_auth_line(ts=_HOUR)])
        aggregate_security_metrics(connection, [_auth_line(ts=_HOUR + timedelta(hours=1))])

        rows = LogMetricBucket.objects.filter(connection=connection, metric="auth_failure")
        assert rows.count() == 2
        assert {r.bucket_start for r in rows} == {_HOUR, _HOUR + timedelta(hours=1)}

    def test_minutes_are_truncated_to_the_hour(self, connection):
        from infrastructure.persistence.integrations.models import LogMetricBucket

        aggregate_security_metrics(
            connection,
            [_auth_line(ts=_HOUR + timedelta(minutes=12)), _auth_line(ts=_HOUR + timedelta(minutes=48))],
        )
        row = LogMetricBucket.objects.get(connection=connection, metric="auth_failure")
        assert row.count == 2
        assert row.bucket_start == _HOUR

    def test_total_volume_counts_every_record(self, connection):
        from infrastructure.persistence.integrations.models import LogMetricBucket

        summary = aggregate_security_metrics(connection, [_auth_line(), _error_line()])
        assert summary["records"] == 2
        total = sum(r.count for r in LogMetricBucket.objects.filter(connection=connection, metric="total_volume"))
        assert total == 2

    def test_record_without_timestamp_falls_back_to_now(self, connection):
        from infrastructure.persistence.integrations.models import LogMetricBucket

        msg = "Failed password for root"
        aggregate_security_metrics(connection, [LogRecord(service="web", level="INFO", message=msg, raw=msg)])
        row = LogMetricBucket.objects.get(connection=connection, metric="auth_failure")
        assert abs((row.bucket_start - datetime.now(UTC)).total_seconds()) < 3700


@pytest.mark.django_db
class TestQueryMetric:
    def _seed(self, connection):
        records = [
            _auth_line(ip="203.0.113.9", ts=_HOUR, service="web"),
            _auth_line(ip="203.0.113.9", ts=_HOUR, service="web"),
            _auth_line(ip="198.51.100.7", ts=_HOUR + timedelta(hours=2), service="auth-svc"),
            _error_line(ts=_HOUR + timedelta(days=1)),
        ]
        aggregate_security_metrics(connection, records)

    def test_total_and_group_by_service(self, connection):
        from components.integrations.application.log_metrics_query_service import query_metric

        self._seed(connection)
        result = query_metric(connection.workspace_id, "auth_failure", window_hours=_window_hours(), group_by="service")
        assert result["total"] == 3
        assert result["rows"][0] == {"service": "web", "count": 2}
        assert {"service": "auth-svc", "count": 1} in result["rows"]

    def test_group_by_source_excludes_blank(self, connection):
        from components.integrations.application.log_metrics_query_service import query_metric

        self._seed(connection)
        # app_error rows carry source="" — a source grouping must be empty.
        result = query_metric(connection.workspace_id, "app_error", window_hours=_window_hours(), group_by="source")
        assert result["total"] == 1
        assert result["rows"] == []

    def test_group_by_hour_and_day(self, connection):
        from components.integrations.application.log_metrics_query_service import query_metric

        self._seed(connection)
        by_hour = query_metric(connection.workspace_id, "auth_failure", window_hours=_window_hours(), group_by="hour")
        assert [r["count"] for r in by_hour["rows"]] == [2, 1]
        by_day = query_metric(connection.workspace_id, "ssh", window_hours=_window_hours(), group_by="day")
        assert sum(r["count"] for r in by_day["rows"]) == 3

    def test_window_filter_excludes_old_buckets(self, connection):
        from components.integrations.application.log_metrics_query_service import query_metric

        self._seed(connection)
        result = query_metric(connection.workspace_id, "auth_failure", window_hours=1)
        assert result["total"] == 0

    def test_unknown_metric_and_group_by_raise(self, connection):
        from components.integrations.application.log_metrics_query_service import query_metric

        with pytest.raises(ValueError):
            query_metric(connection.workspace_id, "bananas")
        with pytest.raises(ValueError):
            query_metric(connection.workspace_id, "auth_failure", group_by="galaxy")

    def test_workspace_isolation(self, connection, workspace_factory):
        from components.integrations.application.log_metrics_query_service import query_metric

        self._seed(connection)
        other = workspace_factory()
        result = query_metric(other.id, "auth_failure", window_hours=_window_hours())
        assert result["total"] == 0


@pytest.mark.django_db
class TestTopSourcesAndTrend:
    def test_top_sources_ranked(self, connection):
        from components.integrations.application.log_metrics_query_service import top_sources

        records = [_auth_line(ip="203.0.113.9") for _ in range(3)]
        records += [_auth_line(ip="198.51.100.7")]
        aggregate_security_metrics(connection, records)

        result = top_sources(connection.workspace_id, "ssh", window_hours=_window_hours(), limit=10)
        assert result["sources"][0] == {"source": "203.0.113.9", "count": 3}
        assert result["sources"][1] == {"source": "198.51.100.7", "count": 1}

    def test_classify_trend_reads_real_buckets(self, connection):
        from components.integrations.application.log_metrics_query_service import classify_trend

        # A burst hour of auth failures over an otherwise quiet window.
        records = [_auth_line(ts=_HOUR) for _ in range(50)]
        aggregate_security_metrics(connection, records)

        result = classify_trend(connection.workspace_id, "auth_failure", window_hours=_window_hours())
        assert result["pattern"] == "spike"
        assert result["total"] == 50
        assert result["max_hour_count"] == 50


@pytest.mark.django_db
class TestIngestWiringFailureSafety:
    def _window(self):
        msg = "ERROR boom"
        rec = LogRecord(service="web", level="ERROR", message=msg, raw=msg, ts=_HOUR)
        return [(rec, "logs/2026/window.json.gz")]

    def test_scan_connection_feeds_buckets(self, connection):
        from components.integrations.application.log_ingest_service import scan_connection
        from infrastructure.persistence.integrations.models import LogMetricBucket

        with mock.patch(f"{_INGEST}.iter_window_records", return_value=self._window()):
            result = scan_connection(connection, only_new=False)

        assert result.records_parsed == 1
        assert LogMetricBucket.objects.filter(connection=connection, metric="app_error").exists()
        assert LogMetricBucket.objects.filter(connection=connection, metric="total_volume").exists()

    def test_aggregation_failure_never_breaks_ingestion(self, connection):
        from components.integrations.application.log_ingest_service import scan_connection
        from infrastructure.persistence.integrations.models import IngestCheckpoint

        with (
            mock.patch(f"{_INGEST}.iter_window_records", return_value=self._window()),
            mock.patch(
                f"{_METRICS}.aggregate_security_metrics",
                side_effect=RuntimeError("aggregation exploded"),
            ),
        ):
            result = scan_connection(connection, only_new=True)

        # Error detection and checkpoint advancement are untouched.
        assert result.records_parsed == 1
        assert len(result.errors) == 1
        checkpoint = IngestCheckpoint.objects.get(connection=connection)
        assert checkpoint.last_object_key == "logs/2026/window.json.gz"


@pytest.mark.django_db
class TestModelTaxonomyLockstep:
    def test_model_choices_match_service_metrics(self):
        from infrastructure.persistence.integrations.models import LogMetricBucket

        assert {c for c, _ in LogMetricBucket.Metric.choices} == set(SECURITY_METRICS)


def _window_hours() -> int:
    """A window wide enough to include the fixed ``_HOUR`` regardless of when
    the suite runs (buckets are filtered relative to ``now``)."""
    return max(int((datetime.now(UTC) - _HOUR).total_seconds() // 3600) + 48, 48)

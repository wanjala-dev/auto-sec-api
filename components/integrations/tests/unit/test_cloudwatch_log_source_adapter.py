"""Unit tests for CloudWatchLogSourceAdapter (ADR 0008 D5, Phase 4).

The assume-role plumbing is shared boto3 wiring; these patch ``_client`` and
exercise the FilterLogEvents read/parse/normalize + verify behaviour — the proof
the LogSourcePort seam generalizes to a non-S3 source.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.ports.log_source_port import LogWindow
from components.integrations.infrastructure.adapters.log_sources.cloudwatch_log_source_adapter import (
    CloudWatchLogSourceAdapter,
)

_CONFIG = {
    "management_account_id": "123456789012",
    "role_name": "AutoSecAuditRole",
    "external_id": "ext-1",
    "log_group": "/aws/lambda/acme",
    "region": "us-east-1",
    "source_id": "src-cw",
}


def _fake_logs(events, next_token=None):
    client = mock.MagicMock()
    resp = {"events": events}
    if next_token:
        resp["nextToken"] = next_token
    client.filter_log_events.return_value = resp
    return client


@pytest.mark.unit
class TestCloudWatchRead:
    def test_read_window_parses_normalizes_and_stamps_source(self):
        events = [
            {"message": "ERROR boom", "logStreamName": "api/abc", "timestamp": 1_700_000_000_000},
            {"message": "just info", "logStreamName": "api/abc", "timestamp": 1_700_000_001_000},
        ]
        adapter = CloudWatchLogSourceAdapter()
        with mock.patch.object(adapter, "_client", return_value=_fake_logs(events, next_token="tok-2")):
            window = adapter.read_window(_CONFIG, since="", limit=10)

        assert isinstance(window, LogWindow)
        assert window.objects_scanned == 2
        assert window.cursor == "tok-2"
        assert len(window.records) == 2

        first = window.records[0]
        assert first.level == "ERROR"  # marker-detected (CloudWatch has no structured level)
        assert first.message == "ERROR boom"
        assert first.service == "api/abc"
        assert first.ts is not None
        assert first.source_kind == "cloudwatch"
        assert first.source_id == "src-cw"
        assert window.records[1].level == "INFO"

    def test_since_passes_next_token_and_empty_page_keeps_cursor(self):
        adapter = CloudWatchLogSourceAdapter()
        client = _fake_logs([], next_token=None)
        with mock.patch.object(adapter, "_client", return_value=client):
            window = adapter.read_window(_CONFIG, since="prev-tok", limit=10)

        assert client.filter_log_events.call_args.kwargs.get("nextToken") == "prev-tok"
        assert window.objects_scanned == 0
        assert window.cursor == "prev-tok"  # never rewinds on an idle poll


@pytest.mark.unit
class TestCloudWatchVerify:
    def test_blank_log_group_is_unhealthy(self):
        health = CloudWatchLogSourceAdapter().verify({"log_group": ""})
        assert health.ok is False
        assert "log group" in health.detail.lower()

    def test_verify_ok_probes_filter_log_events(self):
        adapter = CloudWatchLogSourceAdapter()
        client = mock.MagicMock()
        with mock.patch.object(adapter, "_client", return_value=client):
            health = adapter.verify(_CONFIG)
        assert health.ok is True
        client.filter_log_events.assert_called_once()
        assert client.filter_log_events.call_args.kwargs.get("limit") == 1

    def test_verify_failure_is_scrubbed_not_raised(self):
        adapter = CloudWatchLogSourceAdapter()
        client = mock.MagicMock()
        client.filter_log_events.side_effect = RuntimeError("AccessDenied for log group")
        with mock.patch.object(adapter, "_client", return_value=client):
            health = adapter.verify(_CONFIG)
        assert health.ok is False
        assert "AccessDenied" in health.detail

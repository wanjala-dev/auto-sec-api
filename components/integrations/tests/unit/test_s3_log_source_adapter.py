"""Unit tests for S3LogSourceAdapter (ADR 0008 D5).

The assume-role plumbing is boto3 wiring (integration-covered live); these tests
patch ``_client`` and exercise the read/parse/normalize behaviour that used to
live inline in ``log_ingest_service`` — proving the extraction is faithful.
"""

from __future__ import annotations

import gzip
import json
from unittest import mock

import pytest

from components.integrations.application.ports.log_source_port import LogWindow
from components.integrations.infrastructure.adapters.log_sources.s3_log_source_adapter import (
    S3LogSourceAdapter,
)

_CONFIG = {
    "management_account_id": "123456789012",
    "role_name": "AutoSecAuditRole",
    "external_id": "ext-1",
    "bucket": "acme-logs",
    "prefix": "logs/",
    "source_id": "src-1",
}


def _gz(lines: list[str]) -> bytes:
    return gzip.compress("\n".join(lines).encode())


def _fake_s3(objects: dict[str, list[dict]]):
    """A stub S3 client: paginated list + gunzip-able get_object per key."""
    s3 = mock.MagicMock()
    pager = mock.MagicMock()
    pager.paginate.return_value = [{"Contents": [{"Key": k} for k in objects]}]
    s3.get_paginator.return_value = pager

    def _get(Bucket, Key):
        body = mock.MagicMock()
        body.read.return_value = _gz([json.dumps(d) for d in objects[Key]])
        return {"Body": body}

    s3.get_object.side_effect = _get
    return s3


@pytest.mark.unit
class TestS3LogSourceAdapterRead:
    def test_read_window_parses_normalizes_and_stamps_source(self):
        objects = {
            "logs/dt=2026/1.gz": [
                {
                    "log": '{"level":"ERROR","message":"boom"}',
                    "attrs": {"com.docker.compose.service": "web"},
                    "time": "2026-07-30T00:00:00Z",
                }
            ],
            "logs/dt=2026/2.gz": [{"log": "plain celery line", "attrs": {"com.docker.compose.service": "celery"}}],
        }
        adapter = S3LogSourceAdapter()
        with mock.patch.object(adapter, "_client", return_value=_fake_s3(objects)):
            window = adapter.read_window(_CONFIG, since="", limit=10)

        assert isinstance(window, LogWindow)
        assert window.objects_scanned == 2
        assert window.cursor == "logs/dt=2026/2.gz"  # newest key
        assert len(window.records) == 2

        first = window.records[0]
        assert first.service == "web"
        assert first.level == "ERROR"
        assert first.message == "boom"
        assert first.ts is not None
        assert first.source_kind == "s3"
        assert first.source_id == "src-1"

        # A non-JSON inner log stays INFO with the raw line as the message.
        second = window.records[1]
        assert second.service == "celery"
        assert second.level == "INFO"
        assert second.message == "plain celery line"

    def test_since_cursor_skips_already_processed_keys(self):
        objects = {
            "logs/a.gz": [{"log": "x", "attrs": {}}],
            "logs/b.gz": [{"log": "y", "attrs": {}}],
        }
        adapter = S3LogSourceAdapter()
        with mock.patch.object(adapter, "_client", return_value=_fake_s3(objects)):
            window = adapter.read_window(_CONFIG, since="logs/a.gz", limit=10)

        assert window.objects_scanned == 1
        assert window.cursor == "logs/b.gz"
        assert len(window.records) == 1

    def test_empty_window_returns_since_as_cursor(self):
        adapter = S3LogSourceAdapter()
        with mock.patch.object(adapter, "_client", return_value=_fake_s3({})):
            window = adapter.read_window(_CONFIG, since="logs/a.gz", limit=10)

        assert window.objects_scanned == 0
        assert window.records == ()
        assert window.cursor == "logs/a.gz"  # unchanged — no regression of the checkpoint


@pytest.mark.unit
class TestS3LogSourceAdapterVerify:
    def test_blank_bucket_is_unhealthy_without_calling_aws(self):
        health = S3LogSourceAdapter().verify({"bucket": ""})
        assert health.ok is False
        assert "bucket" in health.detail.lower()

    def test_verify_ok_probes_with_maxkeys_one(self):
        adapter = S3LogSourceAdapter()
        s3 = mock.MagicMock()
        with mock.patch.object(adapter, "_client", return_value=s3):
            health = adapter.verify(_CONFIG)
        assert health.ok is True
        s3.list_objects_v2.assert_called_once()
        assert s3.list_objects_v2.call_args.kwargs.get("MaxKeys") == 1

    def test_verify_failure_is_scrubbed_not_raised(self):
        adapter = S3LogSourceAdapter()
        s3 = mock.MagicMock()
        s3.list_objects_v2.side_effect = RuntimeError("AccessDenied for role")
        with mock.patch.object(adapter, "_client", return_value=s3):
            health = adapter.verify(_CONFIG)
        assert health.ok is False
        assert "AccessDenied" in health.detail

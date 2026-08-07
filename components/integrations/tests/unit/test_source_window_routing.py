"""Unit tests for the multi-source ingest read seam (ADR 0008 D6).

``read_source_windows`` must resolve each active source's adapter from the
``LogSourceProvider`` registry BY THE SOURCE'S KIND — the same resolution the
verify path uses — so an ACTIVE CloudWatch source is read exactly like the S3
one (the closed gap: the old ``read_source_window`` hardcoded "s3" and never
read anything else). Hermetic: fake source rows are passed in via ``sources``
(no ORM) and the registry is a custom ``LogSourceProvider``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from components.integrations.application.log_ingest_service import (
    FALLBACK_SOURCE_ID,
    LogRecord,
    read_source_window,
    read_source_windows,
)
from components.integrations.application.ports.log_source_port import LogSourcePort, LogWindow
from components.integrations.application.providers.log_source_provider import LogSourceProvider

_PROVIDER_MODULE = "components.integrations.application.providers.log_source_provider"


def _connection(trail_s3_bucket: str = ""):
    return SimpleNamespace(
        id="conn-1",
        management_account_id="123456789012",
        role_name="AutoSecAuditRole",
        external_id="ext-1",
        trail_s3_bucket=trail_s3_bucket,
        trail_s3_prefix="logs/",
    )


def _s3_source():
    return SimpleNamespace(
        id="src-s3",
        kind="s3",
        cursor="",
        config={"aws_connection_id": "conn-1", "bucket": "acme-logs", "prefix": "logs/"},
    )


def _cw_source():
    return SimpleNamespace(
        id="src-cw",
        kind="cloudwatch",
        cursor="",
        config={"aws_connection_id": "conn-1", "log_group": "/aws/lambda/acme", "region": "eu-west-1"},
    )


class _RecordingAdapter(LogSourcePort):
    """Records every read; serves one record stamped with the adapter's kind."""

    def __init__(self, kind: str):
        self.kind = kind
        self.calls: list[tuple[dict, str, int]] = []

    def read_window(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow:
        self.calls.append((config, since, limit))
        record = LogRecord(service=self.kind, level="INFO", message="m", raw="m", source_kind=self.kind)
        return LogWindow(records=(record,), cursor=f"{self.kind}-cursor", objects_scanned=1)


def _providers(**adapters):
    provider = LogSourceProvider(sources=adapters)
    return mock.patch(f"{_PROVIDER_MODULE}.get_log_source_provider", return_value=provider)


@pytest.mark.unit
class TestRegistryRouting:
    def test_each_source_is_read_through_its_kinds_adapter(self):
        s3, cw = _RecordingAdapter("s3"), _RecordingAdapter("cloudwatch")
        with _providers(s3=s3, cloudwatch=cw):
            windows = read_source_windows(_connection(), sources=[_s3_source(), _cw_source()])

        assert [(w.source_id, w.kind) for w in windows] == [("src-s3", "s3"), ("src-cw", "cloudwatch")]
        assert len(s3.calls) == 1 and len(cw.calls) == 1
        # Per-kind config resolution (the canonical resolver shared with verify):
        s3_config = s3.calls[0][0]
        assert s3_config["bucket"] == "acme-logs"
        assert s3_config["source_id"] == "src-s3"
        assert s3_config["management_account_id"] == "123456789012"
        cw_config = cw.calls[0][0]
        assert cw_config["log_group"] == "/aws/lambda/acme"
        assert cw_config["region"] == "eu-west-1"
        assert cw_config["source_id"] == "src-cw"
        assert cw_config["external_id"] == "ext-1"

    def test_per_source_cursors_are_passed_to_the_right_adapter(self):
        s3, cw = _RecordingAdapter("s3"), _RecordingAdapter("cloudwatch")
        with _providers(s3=s3, cloudwatch=cw):
            read_source_windows(
                _connection(),
                sources=[_s3_source(), _cw_source()],
                since_by_source={"src-s3": "logs/key-9.gz", "src-cw": "tok-42"},
                max_objects=7,
            )

        assert s3.calls[0][1] == "logs/key-9.gz"
        assert cw.calls[0][1] == "tok-42"
        assert {call[2] for call in s3.calls + cw.calls} == {7}

    def test_unregistered_kind_is_skipped_and_the_rest_still_read(self):
        # CloudWatch flag off → adapter absent from the registry: the source is
        # logged + skipped, never fatal to the S3 read.
        s3 = _RecordingAdapter("s3")
        with _providers(s3=s3):
            windows = read_source_windows(_connection(), sources=[_cw_source(), _s3_source()])

        assert [w.kind for w in windows] == ["s3"]
        assert len(s3.calls) == 1

    def test_no_source_rows_falls_back_to_the_deprecated_trail_fields(self):
        s3 = _RecordingAdapter("s3")
        with _providers(s3=s3):
            windows = read_source_windows(
                _connection(trail_s3_bucket="legacy-bucket"),
                sources=[],
                since_by_source={FALLBACK_SOURCE_ID: "logs/old-key.gz"},
            )

        assert [(w.source_id, w.kind, w.source) for w in windows] == [(FALLBACK_SOURCE_ID, "s3", None)]
        config, since, _ = s3.calls[0]
        assert config["bucket"] == "legacy-bucket"
        assert config["source_id"] == ""
        assert since == "logs/old-key.gz"

    def test_nothing_configured_reads_nothing(self):
        s3 = _RecordingAdapter("s3")
        with _providers(s3=s3):
            assert read_source_windows(_connection(), sources=[]) == []
        assert s3.calls == []


@pytest.mark.unit
class TestMergedWindow:
    def test_read_source_window_merges_all_sources_records(self):
        s3, cw = _RecordingAdapter("s3"), _RecordingAdapter("cloudwatch")
        with (
            _providers(s3=s3, cloudwatch=cw),
            mock.patch(
                "components.integrations.infrastructure.repositories.log_source_repository.LogSourceRepository"
            ) as repo,
        ):
            repo.return_value.active_sources_for_connection.return_value = [_s3_source(), _cw_source()]
            window = read_source_window(_connection(), max_objects=5)

        assert window.objects_scanned == 2
        assert [r.source_kind for r in window.records] == ["s3", "cloudwatch"]
        # A merged window carries no cursor — one cursor can't represent N sources.
        assert window.cursor == ""
        # The aggregator's seam is cursor-free: full-window reads, since="".
        assert s3.calls[0][1] == "" and cw.calls[0][1] == ""

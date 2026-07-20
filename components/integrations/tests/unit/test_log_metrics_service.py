"""Unit tests for the security-metric classifier + trend heuristic.

Pure functions only — no DB, no Django fixtures. Covers every metric class,
multi-metric lines, source-IP extraction, negative cases, metric-name
normalization, and the spike/sustained/quiet heuristic over synthetic hourly
buckets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from components.integrations.application.log_ingest_service import LogRecord
from components.integrations.application.log_metrics_service import (
    APP_ERROR,
    APP_WARNING,
    AUTH_FAILURE,
    HTTP_4XX,
    HTTP_5XX,
    SCANNER,
    SECURITY_METRICS,
    SQLI_SIGNATURE,
    TOTAL_VOLUME,
    classify_security_metrics,
    classify_trend_from_hourly,
    extract_source_ip,
    normalize_metric,
)


def _record(message, *, level="INFO", service="web", raw=None):
    return LogRecord(service=service, level=level, message=message, raw=raw or message)


def _metrics(record):
    return {m for m, _src in classify_security_metrics(record)}


pytestmark = pytest.mark.unit


class TestClassifier:
    def test_auth_failure_ssh_line(self):
        rec = _record("Failed password for invalid user admin from 203.0.113.9 port 51122 ssh2")
        pairs = dict(classify_security_metrics(rec))
        assert AUTH_FAILURE in pairs
        assert pairs[AUTH_FAILURE] == "203.0.113.9"  # source extracted

    def test_auth_failure_variants(self):
        for msg in (
            "authentication failure; logname= uid=0 euid=0",
            "Login failed for user root",
            "POSSIBLE BREAK-IN ATTEMPT!",
            "error: maximum authentication attempts exceeded for root",
        ):
            assert AUTH_FAILURE in _metrics(_record(msg)), msg

    def test_http_5xx_access_log(self):
        rec = _record('10.0.0.5 - - [18/Jul/2026] "GET /api/health HTTP/1.1" 502 157')
        assert HTTP_5XX in _metrics(rec)
        assert HTTP_4XX not in _metrics(rec)

    def test_http_4xx_structured_status(self):
        rec = _record("request completed status=404 path=/api/none")
        assert HTTP_4XX in _metrics(rec)
        assert HTTP_5XX not in _metrics(rec)

    def test_http_2xx_is_not_flagged(self):
        rec = _record('"GET /api/donations HTTP/1.1" 200 512')
        m = _metrics(rec)
        assert HTTP_4XX not in m and HTTP_5XX not in m

    def test_sqli_signatures(self):
        for msg in (
            "GET /items?id=1 UNION SELECT username,password FROM users",
            "q=' OR '1'='1",
            "payload: 1 or 1=1 --",
            "select * from information_schema.tables",
            "id=1;sleep(5)",
        ):
            assert SQLI_SIGNATURE in _metrics(_record(msg)), msg

    def test_scanner_signatures(self):
        for msg in (
            'GET / HTTP/1.1" 200 "sqlmap/1.7"',
            "User-Agent: Nikto/2.5.0",
            "GET /wp-admin/setup-config.php",
            "GET /.env HTTP/1.1",
            "GET /phpmyadmin/index.php",
        ):
            assert SCANNER in _metrics(_record(msg)), msg

    def test_app_error_by_level_and_traceback(self):
        assert APP_ERROR in _metrics(_record("db connection lost", level="ERROR"))
        assert APP_ERROR in _metrics(_record("boom", level="CRITICAL"))
        assert APP_ERROR in _metrics(_record("x", raw="Traceback (most recent call last):\n  File ..."))

    def test_app_warning_by_level(self):
        m = _metrics(_record("disk almost full", level="WARNING"))
        assert APP_WARNING in m
        assert APP_ERROR not in m

    def test_error_level_does_not_double_count_warning(self):
        m = _metrics(_record("boom", level="ERROR"))
        assert APP_WARNING not in m

    def test_total_volume_always_present(self):
        assert TOTAL_VOLUME in _metrics(_record("plain info line"))
        assert TOTAL_VOLUME in _metrics(_record("Failed password for root"))

    def test_benign_line_is_only_total_volume(self):
        assert _metrics(_record("User session refreshed successfully")) == {TOTAL_VOLUME}

    def test_multi_metric_line(self):
        # A sqlmap probe that 500s: scanner + sqli + 5xx + total.
        rec = _record('"GET /items?id=1 UNION SELECT 1,2 HTTP/1.1" 500 0 "sqlmap/1.7" from 198.51.100.7')
        m = _metrics(rec)
        assert {SCANNER, SQLI_SIGNATURE, HTTP_5XX, TOTAL_VOLUME} <= m

    def test_source_blank_for_app_and_volume_metrics(self):
        rec = _record("boom from 203.0.113.9", level="ERROR")
        pairs = dict(classify_security_metrics(rec))
        assert pairs[APP_ERROR] == ""
        assert pairs[TOTAL_VOLUME] == ""

    def test_source_blank_when_no_ip(self):
        rec = _record("Failed password for root")
        assert dict(classify_security_metrics(rec))[AUTH_FAILURE] == ""


class TestSourceExtraction:
    def test_extracts_first_ipv4(self):
        assert extract_source_ip("from 203.0.113.9 to 10.0.0.1") == "203.0.113.9"

    def test_rejects_out_of_range_octets(self):
        assert extract_source_ip("version 999.888.777.666") == ""

    def test_empty_text(self):
        assert extract_source_ip("") == ""


class TestNormalizeMetric:
    def test_canonical_names_pass_through(self):
        for key in SECURITY_METRICS:
            assert normalize_metric(key) == key

    def test_friendly_aliases(self):
        assert normalize_metric("ssh") == AUTH_FAILURE
        assert normalize_metric("SSH attempts") == AUTH_FAILURE
        assert normalize_metric("5xx") == HTTP_5XX
        assert normalize_metric("sql-injection") == SQLI_SIGNATURE
        assert normalize_metric("errors") == APP_ERROR
        assert normalize_metric("volume") == TOTAL_VOLUME

    def test_unknown_metric_raises_with_taxonomy(self):
        with pytest.raises(ValueError) as exc:
            normalize_metric("bananas")
        assert "auth_failure" in str(exc.value)


def _hours(counts):
    """Build {hour_datetime: count} from a list of counts, newest last."""
    start = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
    return {start + timedelta(hours=i): c for i, c in enumerate(counts) if c}


class TestTrendHeuristic:
    def test_no_data_is_quiet(self):
        result = classify_trend_from_hourly({}, 168)
        assert result["pattern"] == "quiet"
        assert result["total"] == 0

    def test_single_burst_hour_is_spike(self):
        # One hour with 500 events in an otherwise silent day.
        result = classify_trend_from_hourly(_hours([0] * 10 + [500]), 24)
        assert result["pattern"] == "spike"
        assert result["max_hour_count"] == 500
        assert result["total"] == 500

    def test_spike_over_low_background(self):
        counts = [2] * 20 + [400]
        result = classify_trend_from_hourly(_hours(counts), 24)
        assert result["pattern"] == "spike"

    def test_sustained_elevation(self):
        # Elevated across 18 of 24 hours, no dominant hour.
        result = classify_trend_from_hourly(_hours([30] * 18), 24)
        assert result["pattern"] == "sustained"
        assert result["active_hours"] == 18

    def test_sparse_low_activity_is_quiet(self):
        # 3 active hours out of a week, small counts — neither spike nor sustained.
        result = classify_trend_from_hourly(_hours([2, 0, 0, 3, 0, 2]), 168)
        assert result["pattern"] == "quiet"

    def test_small_burst_below_spike_floor_is_quiet(self):
        # A lone hour with 4 events must not read as an attack.
        result = classify_trend_from_hourly(_hours([0, 0, 4]), 168)
        assert result["pattern"] == "quiet"

    def test_evidence_numbers_present(self):
        result = classify_trend_from_hourly(_hours([10] * 20), 24)
        for key in ("total", "window_hours", "active_hours", "max_hour_count", "median_hourly"):
            assert key in result

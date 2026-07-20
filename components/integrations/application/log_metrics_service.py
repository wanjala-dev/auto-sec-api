"""Deterministic security-metric classification + hourly aggregation.

The counting half of "chat with the logs" (posture vision §3.2/§4). Same POC
hard rule as every other log reader: **never run an LLM over the raw log
firehose, and never let an LLM write an aggregate.** Every log record in a
scanned window is classified by pure, module-level compiled regexes into the
security-metric taxonomy (``SECURITY_METRICS``) and folded into hourly
``LogMetricBucket`` rows. Counting/trend questions are then answered by ORM
aggregates over those rows — deterministic numbers the agent can only narrate,
never invent.

Layering: ``classify_security_metrics`` / ``extract_source_ip`` /
``classify_trend_from_hourly`` are pure functions (unit-testable, no Django).
``aggregate_security_metrics`` is the single DB writer (lazy ORM import, same
style as the sibling services). The read side lives in
``log_metrics_query_service``.
"""

from __future__ import annotations

import logging
import re
import statistics
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ── Metric taxonomy ────────────────────────────────────────────────────────
# Canonical metric keys. ``LogMetricBucket.Metric`` (persistence) mirrors these
# literals; ``test_log_metric_buckets.py`` asserts the two stay in lockstep.
AUTH_FAILURE = "auth_failure"
HTTP_5XX = "http_5xx"
HTTP_4XX = "http_4xx"
SQLI_SIGNATURE = "sqli_signature"
SCANNER = "scanner"
APP_ERROR = "app_error"
APP_WARNING = "app_warning"
TOTAL_VOLUME = "total_volume"

SECURITY_METRICS: dict[str, str] = {
    AUTH_FAILURE: "Authentication failures — failed logins, SSH attempts, invalid user, authentication failed.",
    HTTP_5XX: "HTTP 5xx server-error responses.",
    HTTP_4XX: "HTTP 4xx client-error responses.",
    SQLI_SIGNATURE: "SQL-injection-shaped payloads — UNION SELECT, ' OR 1=1, information_schema, sleep(n).",
    SCANNER: "Scanner user agents and probing paths — sqlmap, nikto, nmap, /wp-admin, /.env probes.",
    APP_ERROR: "ERROR/CRITICAL-level application log lines.",
    APP_WARNING: "WARNING-level application log lines.",
    TOTAL_VOLUME: "All log lines — the lines/day and DDoS volume baseline (every record counts here).",
}

# Attack-shaped metrics carry the derived source IP so ``top_sources`` can
# answer "where did the attacks come from". App-health metrics + the volume
# baseline keep source="" to bound row cardinality.
_SOURCE_BEARING_METRICS = frozenset({AUTH_FAILURE, HTTP_5XX, HTTP_4XX, SQLI_SIGNATURE, SCANNER})

# Friendly-name coercion so the agent (and the LLM behind it) can say "ssh"
# or "5xx" without memorising the canonical keys.
METRIC_ALIASES: dict[str, str] = {
    **{m: m for m in SECURITY_METRICS},
    "ssh": AUTH_FAILURE,
    "ssh_attempts": AUTH_FAILURE,
    "ssh_attempt": AUTH_FAILURE,
    "auth": AUTH_FAILURE,
    "auth_failures": AUTH_FAILURE,
    "login_failures": AUTH_FAILURE,
    "failed_logins": AUTH_FAILURE,
    "brute_force": AUTH_FAILURE,
    "5xx": HTTP_5XX,
    "server_errors": HTTP_5XX,
    "4xx": HTTP_4XX,
    "client_errors": HTTP_4XX,
    "sqli": SQLI_SIGNATURE,
    "sql_injection": SQLI_SIGNATURE,
    "sql_injections": SQLI_SIGNATURE,
    "scanners": SCANNER,
    "probes": SCANNER,
    "scanning": SCANNER,
    "errors": APP_ERROR,
    "app_errors": APP_ERROR,
    "warnings": APP_WARNING,
    "app_warnings": APP_WARNING,
    "total": TOTAL_VOLUME,
    "volume": TOTAL_VOLUME,
    "all": TOTAL_VOLUME,
    "lines": TOTAL_VOLUME,
}


def normalize_metric(value) -> str:
    """Coerce a friendly metric name to its canonical key.

    Raises the shared-kernel ``ValidationError`` (a ``ValueError`` subclass,
    so boundary code catching ``ValueError`` keeps working) on unknown names.
    """
    from components.shared_kernel.domain.errors import ValidationError

    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in METRIC_ALIASES:
        return METRIC_ALIASES[key]
    raise ValidationError(f"Unknown metric {value!r}. Valid metrics: {', '.join(sorted(SECURITY_METRICS))}.")


# ── Classification regexes (module-level, compiled once) ───────────────────
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b")

_AUTH_FAILURE_RE = re.compile(
    r"(failed\s+password|invalid\s+user|authentication\s+fail(?:ed|ure)|auth\s+fail(?:ed|ure)"
    r"|failed\s+login|login\s+fail(?:ed|ure)|incorrect\s+password|possible\s+break-in"
    r"|pam_unix\(sshd:auth\)|maximum\s+authentication\s+attempts)",
    re.I,
)

# HTTP status extraction — access-log shape (`"GET / HTTP/1.1" 502`) or
# structured key=value (`status=502` / `status_code: 502`).
_HTTP_ACCESS_STATUS_RE = re.compile(r'HTTP/\d(?:\.\d)?"?\s+(?P<status>[1-5]\d{2})\b')
_HTTP_KV_STATUS_RE = re.compile(r'\bstatus(?:_code)?["\s]*[=:]["\s]*(?P<status>[1-5]\d{2})\b', re.I)

_SQLI_RE = re.compile(
    r"(union(?:\s|\+|%20)+(?:all(?:\s|\+|%20)+)?select"
    r"|'\s*or\s*'?1'?\s*=\s*'?1"
    r"|\bor\s+1\s*=\s*1\b"
    r"|information_schema"
    r"|sleep\s*\(\s*\d+\s*\)"
    r"|;\s*drop\s+table"
    r"|xp_cmdshell"
    r"|%27\s*or\s)",
    re.I,
)

_SCANNER_RE = re.compile(
    r"(sqlmap|nikto|nmap|masscan|dirbuster|gobuster|wpscan|zgrab|acunetix|nessus|nuclei"
    r"|/wp-admin|/wp-login|/xmlrpc\.php|/\.env\b|/\.git\b|/phpmyadmin|/etc/passwd|/cgi-bin/)",
    re.I,
)

_ERROR_LEVELS = frozenset({"ERROR", "CRITICAL", "FATAL"})
_WARNING_LEVELS = frozenset({"WARNING", "WARN"})
_TRACEBACK_MARKER = "Traceback (most recent call last)"


def extract_source_ip(text: str) -> str:
    """Return the first IPv4 address in ``text``, or "" when none is present."""
    match = _IPV4_RE.search(text or "")
    return match.group(0) if match else ""


def _http_status(text: str) -> int | None:
    match = _HTTP_ACCESS_STATUS_RE.search(text) or _HTTP_KV_STATUS_RE.search(text)
    return int(match.group("status")) if match else None


def classify_security_metrics(record) -> list[tuple[str, str]]:
    """Classify one ``LogRecord`` into ``[(metric, source), …]`` — pure regex.

    A line can match multiple metrics (a sqlmap probe that 500s is SCANNER +
    SQLI_SIGNATURE + HTTP_5XX + TOTAL_VOLUME). ``TOTAL_VOLUME`` is always
    present. ``source`` is the derived IPv4 for attack-shaped metrics and ""
    otherwise. Deterministic — no LLM, no I/O.
    """
    text = f"{record.message}\n{record.raw}" if record.raw != record.message else (record.raw or record.message)
    level = (record.level or "").upper()
    ip = extract_source_ip(text)

    metrics: list[str] = []
    if _AUTH_FAILURE_RE.search(text):
        metrics.append(AUTH_FAILURE)
    status = _http_status(text)
    if status is not None:
        if 500 <= status <= 599:
            metrics.append(HTTP_5XX)
        elif 400 <= status <= 499:
            metrics.append(HTTP_4XX)
    if _SQLI_RE.search(text):
        metrics.append(SQLI_SIGNATURE)
    if _SCANNER_RE.search(text):
        metrics.append(SCANNER)
    if level in _ERROR_LEVELS or _TRACEBACK_MARKER in text:
        metrics.append(APP_ERROR)
    elif level in _WARNING_LEVELS:
        metrics.append(APP_WARNING)
    metrics.append(TOTAL_VOLUME)

    return [(m, ip if m in _SOURCE_BEARING_METRICS else "") for m in metrics]


def _bucket_hour(ts: datetime | None) -> datetime:
    """Hour-truncate ``ts`` (UTC); fall back to ingestion time when the record
    carried no parseable timestamp."""
    if ts is None:
        ts = datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def aggregate_security_metrics(connection, records) -> dict:
    """Bucket ``records`` by (metric, service, source, hour) and upsert
    ``LogMetricBucket`` rows via the bucket repository (row-count-safe ``F()``
    increments — never read-modify-write).

    Deterministic, LLM-free. Returns a summary dict for logging/telemetry.
    """
    from components.integrations.infrastructure.repositories import log_metric_bucket_repository

    counts: dict[tuple[str, str, str, datetime], int] = {}
    samples: dict[tuple[str, str, str, datetime], str] = {}
    records_seen = 0
    for record in records:
        records_seen += 1
        hour = _bucket_hour(getattr(record, "ts", None))
        for metric, source in classify_security_metrics(record):
            key = (metric, record.service or "", source, hour)
            counts[key] = counts.get(key, 0) + 1
            if key not in samples:
                samples[key] = (record.message or "")[:500]

    by_metric: dict[str, int] = {}
    for (metric, service, source, hour), n in counts.items():
        log_metric_bucket_repository.upsert_bucket(
            connection,
            metric=metric,
            service=service,
            source=source,
            bucket_start=hour,
            count=n,
            sample_message=samples[(metric, service, source, hour)],
        )
        by_metric[metric] = by_metric.get(metric, 0) + n

    summary = {"records": records_seen, "buckets_upserted": len(counts), "by_metric": by_metric}
    logger.info(
        "log_metrics_aggregated connection_id=%s records=%s buckets=%s",
        connection.id,
        records_seen,
        len(counts),
    )
    return summary


# ── Trend heuristic (pure — the query service wraps this over real buckets) ─

# A lone busy hour must clear this floor before it can be called a spike —
# otherwise 3 lines in one hour of an otherwise-silent week reads as an attack.
MIN_SPIKE_COUNT = 10
# Spike: the loudest hour is > 4x the median hour (median over ALL window
# hours, zeros included) AND the top hours concentrate most of the volume.
SPIKE_MEDIAN_MULTIPLIER = 4
SPIKE_CONCENTRATION = 0.5
# Sustained: activity present in more than half the hours of the window.
SUSTAINED_ACTIVE_SHARE = 0.5


def classify_trend_from_hourly(hourly_counts: dict[datetime, int], window_hours: int) -> dict:
    """Classify hourly counts as spike | sustained | quiet — deterministic.

    ``hourly_counts`` maps bucket_start → count (hours with zero activity may
    simply be absent). The evidence numbers ship in the response so the agent
    states the measurement instead of a vibe.
    """
    window_hours = max(int(window_hours), 1)
    active = {h: c for h, c in hourly_counts.items() if c > 0}
    total = sum(active.values())
    evidence = {
        "total": total,
        "window_hours": window_hours,
        "active_hours": len(active),
        "active_share": round(len(active) / window_hours, 3),
    }
    if total == 0:
        return {"pattern": "quiet", **evidence, "max_hour_count": 0, "median_hourly": 0}

    max_hour, max_count = max(active.items(), key=lambda kv: kv[1])
    # Median over the FULL window (zeros included) — a sparse burst must not
    # inherit a high median from its own few hours.
    padded = sorted(list(active.values()) + [0] * (window_hours - len(active)))[:window_hours]
    median_hourly = statistics.median(padded)
    top_hours = sorted(active.values(), reverse=True)[:3]
    concentration = sum(top_hours) / total

    evidence.update(
        {
            "max_hour_count": max_count,
            "max_hour": max_hour.isoformat(),
            "median_hourly": median_hourly,
            "top3_concentration": round(concentration, 3),
        }
    )

    exceeds_median = max_count > SPIKE_MEDIAN_MULTIPLIER * median_hourly if median_hourly > 0 else True
    if exceeds_median and concentration >= SPIKE_CONCENTRATION and max_count >= MIN_SPIKE_COUNT:
        return {"pattern": "spike", **evidence}
    if len(active) / window_hours > SUSTAINED_ACTIVE_SHARE:
        return {"pattern": "sustained", **evidence}
    return {"pattern": "quiet", **evidence}

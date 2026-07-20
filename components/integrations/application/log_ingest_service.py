"""Deterministic log ingestion + error detection.

The POC's hard rule: NEVER run an LLM over the raw log firehose. This module is
the cheap, deterministic first pass — assume the customer role, read new shipped
batches since the checkpoint, parse records, and flag errors by rule. Only a
CONFIRMED detection is handed to the log-watch AGENT (LLM) for summary + triage.

Idempotent by design: an ``IngestCheckpoint`` cursor per (connection, channel)
tracks the newest object key already processed, so re-runs never re-scan or
double-alert. Records are keyed by content hash for within-batch dedupe.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Rule-based error signals (deterministic — no model). Kept deliberately small
# and explicit; the agent adds nuance downstream.
_ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL"}
_ERROR_MARKERS = ("Traceback (most recent call last)", "Exception", "500 Internal")


@dataclass
class LogRecord:
    service: str
    level: str
    message: str
    raw: str
    # Event time parsed from the shipped line (Docker json-driver ``time``
    # field) — feeds the hourly security-metric buckets. ``None`` when the
    # line carried no parseable timestamp (the aggregator falls back to
    # ingestion time).
    ts: datetime | None = None


@dataclass
class DetectionResult:
    objects_scanned: int = 0
    records_parsed: int = 0
    errors: list[LogRecord] = field(default_factory=list)
    by_service: dict[str, int] = field(default_factory=dict)
    newest_key: str = ""
    # Rolling tail of the most recent records (newest last) — feeds the
    # HUD LOG STREAM card. Capped so the payload stays small.
    tail: list[LogRecord] = field(default_factory=list)


# Docker's json-driver timestamps carry nanoseconds; ``fromisoformat`` wants
# at most microseconds — trim anything beyond 6 fractional digits.
_ISO_FRACTION_TRIM_RE = re.compile(r"(\.\d{6})\d+")


def _parse_record_time(rec: dict) -> datetime | None:
    """Parse the Docker json-driver ``time`` field (best-effort, never raises)."""
    raw_time = rec.get("time") or rec.get("timestamp") or ""
    if not raw_time:
        return None
    try:
        cleaned = _ISO_FRACTION_TRIM_RE.sub(r"\1", str(raw_time).replace("Z", "+00:00"))
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _flatten_record(rec: dict) -> LogRecord:
    """A Docker-json line whose ``log`` field is itself app JSON (web/celery)."""
    service = (rec.get("attrs") or {}).get("com.docker.compose.service", "?")
    inner_raw = rec.get("log") or rec.get("message") or ""
    level, message = "INFO", inner_raw.strip()
    try:
        inner = json.loads(inner_raw)
        if isinstance(inner, dict):
            level = str(inner.get("level") or inner.get("levelname") or "INFO").upper()
            message = str(inner.get("message") or inner.get("msg") or inner_raw)
    except (ValueError, TypeError):
        pass
    return LogRecord(service=service, level=level, message=message[:1000], raw=inner_raw, ts=_parse_record_time(rec))


def _is_error(r: LogRecord) -> bool:
    if r.level in _ERROR_LEVELS:
        return True
    return any(m in r.raw for m in _ERROR_MARKERS)


def _assume_role_s3_client(connection):
    """Assume the customer's read role and return an S3 client scoped to it.

    Extracted so both the error scan (``scan_connection``) and the temporal
    pattern aggregator (``log_pattern_analyzer``) share ONE credential path —
    the assume-role + confused-deputy ``ExternalId`` posture lives in a single
    place, not copy-pasted per reader (DRY; solve once).
    """
    import boto3

    creds = boto3.client("sts").assume_role(
        RoleArn=f"arn:aws:iam::{connection.management_account_id}:role/{connection.role_name}",
        RoleSessionName="autosec-logwatch",
        ExternalId=connection.external_id,
    )["Credentials"]
    return boto3.client(
        "s3",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _list_window_keys(s3, connection, *, max_objects: int, after: str = "") -> list[str]:
    """Return the newest ``max_objects`` object keys under the connection prefix.

    ``after`` (a checkpoint cursor) skips already-processed keys; pass "" for a
    full recent-window read (what the temporal aggregator wants — it needs the
    whole window each run, not just what's new since the last error scan).
    """
    prefix = connection.trail_s3_prefix or "logs/"
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=connection.trail_s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if after and obj["Key"] <= after:
                continue
            keys.append(obj["Key"])
    keys.sort()
    return keys[-max_objects:]  # newest window


def iter_window_records(connection, *, max_objects: int = 20, after: str = ""):
    """Yield ``(LogRecord, object_key)`` for the newest window — no side effects.

    The shared read primitive: assume role → list newest keys → download →
    gunzip → parse each JSON line. Checkpoint-free (the caller decides whether to
    advance a cursor), so the pattern aggregator can re-read overlapping windows
    to observe a pattern SUSTAINED over time without disturbing the error scan's
    cursor.
    """
    s3 = _assume_role_s3_client(connection)
    for key in _list_window_keys(s3, connection, max_objects=max_objects, after=after):
        body = s3.get_object(Bucket=connection.trail_s3_bucket, Key=key)["Body"].read()
        try:
            text = gzip.decompress(body).decode("utf-8", "replace")
        except OSError:
            text = body.decode("utf-8", "replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            yield _flatten_record(rec), key


def scan_connection(connection, *, max_objects: int = 20, only_new: bool = True) -> DetectionResult:
    """Assume the role, read up to ``max_objects`` newest batches, detect errors.

    ``only_new`` advances the IngestCheckpoint so subsequent runs skip already-
    processed keys (the Celery path). Set False for an ad-hoc full re-scan.
    """
    from infrastructure.persistence.integrations.models import IngestCheckpoint

    checkpoint, _ = IngestCheckpoint.objects.get_or_create(
        connection=connection,
        account_id=connection.management_account_id,
        region="",
        channel=IngestCheckpoint.Channel.S3_LIST,
    )
    after = checkpoint.last_object_key if only_new else ""

    result = DetectionResult()
    seen_hashes: set[str] = set()
    seen_keys: set[str] = set()
    window_records: list[LogRecord] = []
    for lr, key in iter_window_records(connection, max_objects=max_objects, after=after):
        if key not in seen_keys:
            seen_keys.add(key)
            result.objects_scanned += 1
        result.newest_key = max(result.newest_key, key)
        result.records_parsed += 1
        result.tail.append(lr)
        if len(result.tail) > 150:
            result.tail.pop(0)
        result.by_service[lr.service] = result.by_service.get(lr.service, 0) + 1
        window_records.append(lr)
        if _is_error(lr):
            h = hashlib.sha256(lr.raw.encode()).hexdigest()[:16]
            if h not in seen_hashes:
                seen_hashes.add(h)
                result.errors.append(lr)

    # Feed the hourly security-metric buckets from the SAME scanned window —
    # every ingest run keeps the "chat with the logs" aggregates fresh with no
    # second S3 read. Failure-safe by design: aggregation is a side-channel,
    # so ANY error here is logged and swallowed — it must never break error
    # detection or checkpoint advancement. (The broad except is the documented
    # log-and-continue exception: ingestion correctness > metrics freshness.)
    if window_records:
        try:
            from components.integrations.application.log_metrics_service import aggregate_security_metrics

            aggregate_security_metrics(connection, window_records)
        except Exception:
            logger.exception("log_metrics_aggregation_failed connection_id=%s", connection.id)

    if only_new and result.newest_key:
        checkpoint.last_object_key = result.newest_key
        checkpoint.objects_processed += result.objects_scanned
        checkpoint.events_processed += result.records_parsed
        checkpoint.save()

    logger.info(
        "logwatch_scan connection_id=%s objects=%s records=%s errors=%s",
        connection.id,
        result.objects_scanned,
        result.records_parsed,
        len(result.errors),
    )
    return result


@dataclass
class ErrorFinding:
    """An evidence-bearing log error finding (the detection half of the
    evidence contract). ``probable_cause`` + ``recommendation`` are left for
    the triage agent (LLM); everything here is deterministic fact the detector
    can stand behind.
    """

    fingerprint: str  # stable hash → idempotency key
    service: str
    level: str
    severity: str  # critical | high | medium
    signal: str  # one-line "what tripped"
    message: str
    evidence: list[dict]  # [{type, detail}] — what the detector actually read
    blast_radius: dict  # {service, level, window_records}
    confidence: str  # high (level-based) | medium (marker-based)

    def as_contract(self) -> dict:
        """The evidence-contract dict stored on the finding's payload."""
        return {
            "signal": self.signal,
            "service": self.service,
            "level": self.level,
            "severity": self.severity,
            "evidence": self.evidence,
            "blast_radius": self.blast_radius,
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
            # Filled in later by the triage agent (LLM-after-detection):
            "probable_cause": "",
            "suggested_fix": "",
            "recommendation": "",
            "triage": {"status": "pending"},
        }


def _severity_for(level: str) -> str:
    return {"CRITICAL": "critical", "FATAL": "critical", "ERROR": "high"}.get(level.upper(), "medium")


def scan_workspace_for_errors(workspace_id, *, max_objects: int = 20, only_new: bool = True) -> list[ErrorFinding]:
    """Resolve the workspace's connected AWS source, scan new log batches, and
    return evidence-bearing error findings.

    The single application entrypoint the LogWatch detector calls — it keeps the
    agents-context detector importing only ``integrations.application`` (never
    integrations persistence), respecting the bounded-context boundary. Returns
    ``[]`` when no source is connected (a workspace with no integration simply
    has nothing to detect).
    """
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    conn = (
        AwsOrganizationConnection.objects.filter(workspace_id=workspace_id, status="connected")
        .order_by("-created_at")
        .first()
    )
    if conn is None:
        return []

    result = scan_connection(conn, max_objects=max_objects, only_new=only_new)
    findings: list[ErrorFinding] = []
    for err in result.errors:
        level = (err.level or "ERROR").upper()
        confidence = "high" if level in _ERROR_LEVELS else "medium"
        fingerprint = hashlib.sha256(err.raw.encode()).hexdigest()[:16]
        findings.append(
            ErrorFinding(
                fingerprint=fingerprint,
                service=err.service,
                level=level,
                severity=_severity_for(level),
                signal=f"{level} in {err.service}",
                message=err.message[:500],
                evidence=[
                    {"type": "log_line", "detail": err.raw[:800]},
                    {"type": "level", "detail": level},
                    {"type": "source_object", "detail": result.newest_key},
                ],
                blast_radius={
                    "service": err.service,
                    "level": level,
                    "window_records": result.records_parsed,
                    "services_in_window": result.by_service,
                },
                confidence=confidence,
            )
        )
    logger.info(
        "logwatch_scan_workspace workspace_id=%s connection_id=%s findings=%s",
        workspace_id,
        conn.id,
        len(findings),
    )
    return findings

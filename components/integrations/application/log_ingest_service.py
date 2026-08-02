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

import hashlib
import logging
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
    # Which log source produced this record (ADR 0008 D2). Lets a merged,
    # multi-source stream self-identify so the HUD/map can group or filter by
    # source. Defaults keep every existing construction valid.
    source_kind: str = ""  # "s3" | "cloudwatch" | "datadog" | "splunk" | …
    source_id: str = ""  # the WorkspaceLogSource id, once sources are first-class


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


def _is_error(r: LogRecord) -> bool:
    if r.level in _ERROR_LEVELS:
        return True
    return any(m in r.raw for m in _ERROR_MARKERS)


def _s3_config_from_connection(connection) -> dict:
    """The S3 source's config: bucket/prefix from the WorkspaceLogSource, creds
    from the AWS connection (ADR 0008 D7).

    The S3 *location* now lives on a first-class ``WorkspaceLogSource`` row, so a
    connection re-verify can no longer blank where logs are read from — the fix
    for the "logs silently stopped" regression. The connection still vends the
    assume-role identity (management account / role / ExternalId). A transitional
    fallback to the deprecated ``trail_s3_*`` fields keeps envs that predate the
    seed migration working; it is removed once every env is migrated.

    The active-source lookup goes through the ``LogSourceRepository`` so this
    application service stays ORM-free (the repository is the only ORM slot).
    """
    from components.integrations.infrastructure.repositories.log_source_repository import (
        LogSourceRepository,
    )

    source = LogSourceRepository().active_s3_source_for_connection(connection)
    return s3_adapter_config(connection, source)


def s3_adapter_config(connection, source=None) -> dict:
    """Assemble the S3 adapter's config: assume-role creds from the AWS connection,
    bucket/prefix from the WorkspaceLogSource (or the deprecated trail fields when
    no source is given). The one canonical place this is built — reused by the read
    path (connection → its source) and by verify (source → its connection).
    """
    if source is not None:
        bucket = source.config.get("bucket", "")
        prefix = source.config.get("prefix") or "logs/"
        source_id = str(source.id)
    else:
        # Deprecated fallback (ADR 0008 D7): the connection's own trail fields.
        bucket = connection.trail_s3_bucket
        prefix = connection.trail_s3_prefix or "logs/"
        source_id = ""

    return {
        "management_account_id": connection.management_account_id,
        "role_name": connection.role_name,
        "external_id": connection.external_id,
        "bucket": bucket,
        "prefix": prefix,
        "source_id": source_id,
    }


def read_source_window(connection, *, max_objects: int = 20, after: str = "") -> LogWindow:
    """Read the newest window of records for a connection's log source(s).

    The shared read seam both the error scan (``scan_connection``) and the
    temporal aggregator (``log_pattern_analyzer``) go through — it resolves the
    source adapter from the provider and drives it via ``LogSourcePort`` (ADR
    0008). Checkpoint-free (the caller decides whether to advance a cursor), so
    the aggregator can re-read overlapping windows without disturbing the error
    scan's cursor. Phase 1: one S3 source per connection.
    """
    from components.integrations.application.providers.log_source_provider import (
        get_log_source_provider,
    )

    source = get_log_source_provider().get("s3")
    return source.read_window(_s3_config_from_connection(connection), since=after, limit=max_objects)


def scan_connection(connection, *, max_objects: int = 20, only_new: bool = True) -> DetectionResult:
    """Assume the role, read up to ``max_objects`` newest batches, detect errors.

    ``only_new`` advances the IngestCheckpoint so subsequent runs skip already-
    processed keys (the Celery path). Set False for an ad-hoc full re-scan.
    The cursor is read/advanced through the ``IngestCheckpointRepository`` so
    this service stays ORM-free.
    """
    from components.integrations.infrastructure.repositories.ingest_checkpoint_repository import (
        IngestCheckpointRepository,
    )

    checkpoint_repo = IngestCheckpointRepository()
    checkpoint = checkpoint_repo.get_or_create_s3_list(connection)
    after = checkpoint.last_object_key if only_new else ""

    window = read_source_window(connection, max_objects=max_objects, after=after)

    result = DetectionResult()
    result.objects_scanned = window.objects_scanned
    result.newest_key = window.cursor
    seen_hashes: set[str] = set()
    window_records: list[LogRecord] = list(window.records)
    for lr in window.records:
        result.records_parsed += 1
        result.tail.append(lr)
        if len(result.tail) > 150:
            result.tail.pop(0)
        result.by_service[lr.service] = result.by_service.get(lr.service, 0) + 1
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
        checkpoint_repo.advance(
            checkpoint,
            last_object_key=result.newest_key,
            objects_processed=result.objects_scanned,
            events_processed=result.records_parsed,
        )

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
    has nothing to detect). The connection is resolved through the
    ``AwsConnectionRepository`` so this service stays ORM-free.
    """
    from components.integrations.infrastructure.repositories.aws_connection_repository import (
        AwsConnectionRepository,
    )

    conn = AwsConnectionRepository().latest_connected_for_workspace(workspace_id)
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

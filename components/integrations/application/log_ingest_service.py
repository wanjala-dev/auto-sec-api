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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # runtime import lives in-function: the port module imports LogRecord from here
    from components.integrations.application.ports.log_source_port import LogWindow

logger = logging.getLogger(__name__)

# Rule-based error signals (deterministic — no model). Kept deliberately small
# and explicit; the agent adds nuance downstream.
_ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL"}
_ERROR_MARKERS = ("Traceback (most recent call last)", "Exception", "500 Internal")

# Source-kind identifiers (mirror ``WorkspaceLogSource.Kind`` values, which are the
# same strings the ``LogSourcePort`` adapters register under). Plain constants so
# the application layer never imports the ORM enum.
KIND_S3 = "s3"
KIND_CLOUDWATCH = "cloudwatch"

# ``SourceWindow.source_id`` for the deprecated ``trail_s3_*`` fallback read (the
# pre-seed-migration shape with no WorkspaceLogSource row behind it).
FALLBACK_SOURCE_ID = ""

# Why an ACTIVE log source is nonetheless not read by the ingest tick. Machine
# readable so an operator can grep one string across every workspace.
INGEST_SKIP_S3_CHECKPOINT_BRIDGE = "s3_checkpoint_bridge_single_source"


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


def cloudwatch_adapter_config(connection, source) -> dict:
    """Assemble the CloudWatch adapter's config: log group/region from the
    WorkspaceLogSource, assume-role identity from the AWS connection. The one
    canonical place this is built — shared by the verify path (LogSourceService)
    and the ingest read path (``read_source_windows``)."""
    config = dict(source.config or {})
    config.update(
        {
            "management_account_id": connection.management_account_id,
            "role_name": connection.role_name,
            "external_id": connection.external_id,
            "source_id": str(source.id),
        }
    )
    return config


def source_adapter_config(connection, source) -> dict:
    """Resolve a ``WorkspaceLogSource`` row into its adapter config — the ONE
    per-kind resolver, shared by verify (``LogSourceService``) and the ingest
    read path. AWS-backed kinds (S3, CloudWatch) take their assume-role identity
    from the connection; other kinds are self-contained (3P secrets ride on
    ``secret_ref``, resolved in a later phase) and ignore ``connection``."""
    if source.kind == KIND_S3:
        return s3_adapter_config(connection, source)
    if source.kind == KIND_CLOUDWATCH:
        return cloudwatch_adapter_config(connection, source)
    config = dict(source.config or {})
    config["source_id"] = str(source.id)
    return config


@dataclass(frozen=True)
class SourceWindow:
    """One source's read in a multi-source ingest tick: which log source produced
    the window, plus the window itself — so the caller can advance each source's
    cursor independently. ``source`` is the WorkspaceLogSource row (opaque to this
    layer; ``None`` for the deprecated ``trail_s3_*`` fallback read)."""

    source_id: str
    kind: str
    window: LogWindow
    source: Any = None


@dataclass(frozen=True)
class SourceIngestDecision:
    """Whether the ingest tick reads one ACTIVE source, and — when it does not —
    the machine-readable reason. ``source`` is the WorkspaceLogSource row (opaque
    to this layer)."""

    source: Any
    ingesting: bool
    skip_reason: str = ""


def decide_source_ingest(active_sources: list) -> list[SourceIngestDecision]:
    """Which of a connection's ACTIVE sources the ingest tick reads — the ONE
    place that decision is made, so it can never be made invisibly again.

    S3 is still capped to the single oldest active source: its ingest cursor
    bridges through the one per-connection ``IngestCheckpoint``, which cannot
    track two buckets. The cap lifts when the S3 cursor migrates onto the
    per-source ``WorkspaceLogSource.cursor`` field (the ADR 0008 "migrate or
    bridge" follow-up). Every other ACTIVE source is read.

    ``active_sources`` must be oldest-first (what ``LogSourceRepository`` returns)
    — "oldest wins" is the stable choice that keeps a live env reading the bucket
    it was already reading.
    """
    first_s3_id = next((s.id for s in active_sources if s.kind == KIND_S3), None)
    decisions: list[SourceIngestDecision] = []
    for source in active_sources:
        capped = source.kind == KIND_S3 and source.id != first_s3_id
        decisions.append(
            SourceIngestDecision(
                source=source,
                ingesting=not capped,
                skip_reason=INGEST_SKIP_S3_CHECKPOINT_BRIDGE if capped else "",
            )
        )
    return decisions


def active_ingest_sources(connection) -> list:
    """The ACTIVE sources this connection's tick reads — with every skipped source
    logged by id, kind and reason.

    An ACTIVE source the tick does not read still renders ACTIVE on the Settings ▸
    Log Sources row, so the skip MUST announce itself: silently dropping it is how
    a customer's second bucket got zero ingestion AND zero signal. The lookup goes
    through ``LogSourceRepository`` so this service stays ORM-free.
    """
    from components.integrations.infrastructure.repositories.log_source_repository import (
        LogSourceRepository,
    )

    sources: list = []
    for decision in decide_source_ingest(LogSourceRepository().active_sources_for_connection(connection)):
        if decision.ingesting:
            sources.append(decision.source)
            continue
        logger.warning(
            "log_source_not_ingested connection_id=%s source_id=%s kind=%s reason=%s",
            connection.id,
            decision.source.id,
            decision.source.kind,
            decision.skip_reason,
        )
    return sources


def read_source_windows(
    connection,
    *,
    max_objects: int = 20,
    since_by_source: dict[str, str] | None = None,
    sources: list | None = None,
) -> list[SourceWindow]:
    """Read the newest window of EVERY active log source behind a connection.

    The shared read seam (ADR 0008 D6): resolves each source's adapter from the
    ``LogSourceProvider`` registry by the source's ``kind`` — the same resolution
    the verify path uses — so an ACTIVE CloudWatch source is read exactly like the
    S3 one, and adding a source kind is an adapter + a registry line, never a
    change here. Checkpoint-free: the caller supplies each source's cursor via
    ``since_by_source`` (keyed by source id) and decides whether to advance it.

    A source whose adapter isn't registered (feature flag off) is logged and
    skipped — never fatal to the other sources. When no source rows exist, falls
    back to the deprecated connection ``trail_s3_*`` fields (pre-seed-migration
    envs; ADR 0008 D7), keyed ``FALLBACK_SOURCE_ID``. ``sources`` lets a caller
    that already fetched the read set (via ``active_ingest_sources``) avoid a
    second lookup.
    """
    from components.integrations.application.providers.log_source_provider import (
        UnsupportedLogSourceError,
        get_log_source_provider,
    )

    provider = get_log_source_provider()
    if sources is None:
        sources = active_ingest_sources(connection)
    since_by_source = since_by_source or {}

    windows: list[SourceWindow] = []
    for source in sources:
        try:
            adapter = provider.get(source.kind)
        except UnsupportedLogSourceError:
            logger.warning(
                "log_source_adapter_unavailable connection_id=%s source_id=%s kind=%s",
                connection.id,
                source.id,
                source.kind,
            )
            continue
        window = adapter.read_window(
            source_adapter_config(connection, source),
            since=since_by_source.get(str(source.id), ""),
            limit=max_objects,
        )
        windows.append(SourceWindow(source_id=str(source.id), kind=source.kind, window=window, source=source))

    if not sources and connection.trail_s3_bucket:
        # Deprecated fallback (ADR 0008 D7): envs that predate the seed migration
        # still read the connection's own trail fields, cursored by the legacy
        # per-connection IngestCheckpoint.
        window = provider.get(KIND_S3).read_window(
            s3_adapter_config(connection, None),
            since=since_by_source.get(FALLBACK_SOURCE_ID, ""),
            limit=max_objects,
        )
        windows.append(SourceWindow(source_id=FALLBACK_SOURCE_ID, kind=KIND_S3, window=window, source=None))
    return windows


def read_source_window(connection, *, max_objects: int = 20) -> LogWindow:
    """Merged, cursor-free read across every active log source of a connection.

    The temporal aggregator's seam (``log_pattern_analyzer``): it re-reads the
    full recent window each run and must never disturb the error scan's cursors.
    The error scan uses ``read_source_windows`` directly (per-source cursors).
    The merged window carries no cursor — a single opaque cursor cannot represent
    N heterogeneous sources.
    """
    from components.integrations.application.ports.log_source_port import LogWindow

    records: list[LogRecord] = []
    objects_scanned = 0
    for sw in read_source_windows(connection, max_objects=max_objects):
        records.extend(sw.window.records)
        objects_scanned += sw.window.objects_scanned
    return LogWindow(records=tuple(records), cursor="", objects_scanned=objects_scanned)


def scan_connection(connection, *, max_objects: int = 20, only_new: bool = True) -> DetectionResult:
    """Read every active log source's newest window, detect errors, advance cursors.

    ``only_new`` advances each source's ingest cursor so subsequent runs skip
    already-processed batches (the Celery path); set False for an ad-hoc full
    re-scan. Cursor storage is per source kind: S3 still bridges through the
    legacy per-connection ``IngestCheckpoint`` (ADR 0008 — "migrate or bridge";
    live envs carry their S3 cursor there), while every other kind advances the
    per-source ``WorkspaceLogSource.cursor`` field the model was given for this.
    All cursor I/O goes through repositories so this service stays ORM-free.
    """
    from components.integrations.infrastructure.repositories.ingest_checkpoint_repository import (
        IngestCheckpointRepository,
    )
    from components.integrations.infrastructure.repositories.log_source_repository import (
        LogSourceRepository,
    )

    checkpoint_repo = IngestCheckpointRepository()
    source_repo = LogSourceRepository()
    checkpoint = checkpoint_repo.get_or_create_s3_list(connection)
    sources = active_ingest_sources(connection)

    since_by_source: dict[str, str] = {}
    if only_new:
        since_by_source[FALLBACK_SOURCE_ID] = checkpoint.last_object_key
        for source in sources:
            since_by_source[str(source.id)] = (
                checkpoint.last_object_key if source.kind == KIND_S3 else (source.cursor or "")
            )

    source_windows = read_source_windows(
        connection, max_objects=max_objects, since_by_source=since_by_source, sources=sources
    )

    result = DetectionResult()
    window_records: list[LogRecord] = []
    s3_objects = s3_records = 0
    for sw in source_windows:
        result.objects_scanned += sw.window.objects_scanned
        window_records.extend(sw.window.records)
        if sw.kind == KIND_S3:
            # ``newest_key`` keeps its historical meaning: the S3 cursor that
            # feeds the IngestCheckpoint bridge (and the finding evidence).
            result.newest_key = sw.window.cursor
            s3_objects += sw.window.objects_scanned
            s3_records += len(sw.window.records)

    seen_hashes: set[str] = set()
    for lr in window_records:
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

    if only_new:
        for sw in source_windows:
            if sw.source is None or sw.kind == KIND_S3:
                continue  # S3 (incl. the trail fallback) advances through the IngestCheckpoint below
            if sw.window.cursor and sw.window.cursor != (sw.source.cursor or ""):
                source_repo.advance_cursor(sw.source, sw.window.cursor)
        if result.newest_key:
            checkpoint_repo.advance(
                checkpoint,
                last_object_key=result.newest_key,
                objects_processed=s3_objects,
                events_processed=s3_records,
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
            # The identity is carried ONCE, as ``lookup_key`` — the detector adds
            # it when it spreads this contract into the board payload, and that
            # is the key every reader uses. A second ``fingerprint`` copy lived
            # here and was what made the two-name drift in ADR 0032 §1.3.3 look
            # survivable. Do not re-add it.
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

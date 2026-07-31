"""LogSourcePort — the seam every log source plugs into (ADR 0008).

A log source (an S3 trail, a CloudWatch log group, a Datadog site, a Splunk index)
is a *system the app reads from*, so it is a driven adapter behind this port. The
port is shaped to the Application Core's need — "tell me you're reachable, and give
me the next window of normalized records" — not to boto3 / the Datadog SDK / the
Splunk REST API. Adding a source kind is a new adapter + a registry line, never a
new ingest pipeline (mirrors ``ScannerPort``; see ADR 0004 rule C5).

Integrations-internal: only the integrations context implements + consumes this,
so — unlike ``ScannerPort`` — it lives here, not in the shared kernel.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.integrations.application.log_ingest_service import LogRecord


@dataclass(frozen=True)
class LogSourceHealth:
    """Result of a reachability probe. ``detail`` is human-readable and MUST NOT
    carry secrets (it surfaces in verify responses)."""

    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class LogWindow:
    """One read of a source: the normalized records plus an opaque, per-source
    checkpoint so the next read is idempotent.

    ``cursor`` generalizes the S3 ``last_object_key`` (CloudWatch nextToken, a
    Datadog/Splunk time cursor, …). ``objects_scanned`` is the number of source
    batches read (S3 objects, CloudWatch pages) — a source-agnostic count the
    ingest pipeline records without knowing the source kind.
    """

    records: tuple[LogRecord, ...]
    cursor: str = ""
    objects_scanned: int = 0


class LogSourcePort:
    """Interface (structural): implement ``verify`` + ``read_window`` to be a log
    source adapter. Kept a plain class (not an ABC) so an adapter can subclass or
    merely duck-type it — the provider wires whichever concrete adapter by kind.
    """

    def verify(self, config: dict) -> LogSourceHealth:
        """Cheap reachability/permission probe for this source's ``config``."""
        raise NotImplementedError

    def read_window(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow:
        """Read the newest window of records after the ``since`` cursor.

        ``config`` is the source's already-secret-resolved settings. ``since=""``
        reads the full recent window (what the temporal aggregator wants);
        ``limit`` caps the number of source batches read.
        """
        raise NotImplementedError

"""CloudWatchLogSourceAdapter — the second LogSourcePort adapter (ADR 0008 D5).

Reads a CloudWatch Logs log group via ``FilterLogEvents`` (pull, ``nextToken``
cursor), through the customer's assume-role identity. The second real adapter —
it proves the port generalizes beyond S3 the way Trivy proved ``ScannerPort``.
Registered behind the ``feature.log_source_cloudwatch`` flag.

``config`` (built by LogSourceService from the source + its AWS connection):
    management_account_id, role_name, external_id  — assume-role identity
    log_group, region                              — which group, which region
    source_id (optional)                           — stamped on each record
"""

from __future__ import annotations

from datetime import UTC, datetime

from components.integrations.application.log_ingest_service import LogRecord
from components.integrations.application.ports.log_source_port import (
    LogSourceHealth,
    LogSourcePort,
    LogWindow,
)

# CloudWatch messages carry no structured level; flag these markers as errors so
# the logwatch detector still surfaces them (mirrors log_ingest's _ERROR_MARKERS).
_ERROR_MARKERS = ("ERROR", "CRITICAL", "FATAL", "EXCEPTION", "TRACEBACK")


class CloudWatchLogSourceAdapter(LogSourcePort):
    """Pull adapter: assume role → FilterLogEvents over a log group."""

    KIND = "cloudwatch"

    def verify(self, config: dict) -> LogSourceHealth:
        log_group = config.get("log_group") or ""
        if not log_group:
            return LogSourceHealth(ok=False, detail="No CloudWatch log group configured.")
        try:
            client = self._client(config)
            client.filter_log_events(logGroupName=log_group, limit=1)
            return LogSourceHealth(ok=True)
        except Exception as exc:
            return LogSourceHealth(ok=False, detail=str(exc)[:200])

    def read_window(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow:
        client = self._client(config)
        source_id = config.get("source_id", "")
        kwargs = {"logGroupName": config["log_group"], "limit": max(1, min(limit, 10000))}
        if since:
            kwargs["nextToken"] = since
        resp = client.filter_log_events(**kwargs)
        events = resp.get("events", [])
        records = tuple(self._to_record(e, source_id=source_id) for e in events)
        # nextToken paginates forward; keep the old cursor when the page is empty
        # so an idle poll never rewinds.
        cursor = resp.get("nextToken") or since
        return LogWindow(records=records, cursor=cursor, objects_scanned=len(events))

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _client(config: dict):
        from components.integrations.infrastructure.adapters.log_sources._aws_creds import (
            assume_role_client,
        )

        return assume_role_client(config, "logs", region=config.get("region") or "us-east-1")

    @classmethod
    def _to_record(cls, event: dict, *, source_id: str = "") -> LogRecord:
        message = str(event.get("message") or "").strip()
        upper = message.upper()
        level = "ERROR" if any(m in upper for m in _ERROR_MARKERS) else "INFO"
        ts = None
        raw_ts = event.get("timestamp")  # ms since epoch
        if raw_ts:
            try:
                ts = datetime.fromtimestamp(raw_ts / 1000, tz=UTC)
            except (ValueError, OSError, TypeError):
                ts = None
        return LogRecord(
            service=event.get("logStreamName") or "cloudwatch",
            level=level,
            message=message[:1000],
            raw=message,
            ts=ts,
            source_kind=cls.KIND,
            source_id=source_id,
        )

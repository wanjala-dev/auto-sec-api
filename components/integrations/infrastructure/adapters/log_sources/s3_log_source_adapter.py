"""S3LogSourceAdapter — the first LogSourcePort adapter (ADR 0008 D5).

Reads shipped logs from an S3 prefix by assuming the customer's read role (the
confused-deputy ``ExternalId`` posture), listing the newest window of objects,
downloading + gunzipping them, and parsing each JSON line into the normalized
``LogRecord``. This is the read path that previously lived inline in
``log_ingest_service`` — moved here so it is one adapter behind the port,
reused by the error scan and the temporal pattern aggregator (DRY; solve once).

``config`` (built by the caller from the connection / a WorkspaceLogSource):
    management_account_id, role_name, external_id  — assume-role identity
    bucket, prefix                                 — where the logs live
    source_id (optional)                           — stamped on each record
"""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime

from components.integrations.application.log_ingest_service import LogRecord
from components.integrations.application.ports.log_source_port import (
    LogSourceHealth,
    LogSourcePort,
    LogWindow,
)

# Docker's json-driver timestamps carry nanoseconds; ``fromisoformat`` wants at
# most microseconds — trim anything beyond 6 fractional digits.
_ISO_FRACTION_TRIM_RE = re.compile(r"(\.\d{6})\d+")


class S3LogSourceAdapter(LogSourcePort):
    """Pull adapter: assume role → list newest window → get + gunzip → parse."""

    KIND = "s3"

    def verify(self, config: dict) -> LogSourceHealth:
        bucket = config.get("bucket") or ""
        if not bucket:
            return LogSourceHealth(ok=False, detail="No S3 bucket configured.")
        try:
            s3 = self._client(config)
            s3.list_objects_v2(Bucket=bucket, Prefix=config.get("prefix") or "logs/", MaxKeys=1)
            return LogSourceHealth(ok=True)
        except Exception as exc:
            return LogSourceHealth(ok=False, detail=str(exc)[:200])

    def read_window(self, config: dict, *, since: str = "", limit: int = 500) -> LogWindow:
        s3 = self._client(config)
        bucket = config["bucket"]
        source_id = config.get("source_id", "")
        keys = self._list_window_keys(s3, config, max_objects=limit, after=since)
        records: list[LogRecord] = []
        for key in keys:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
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
                records.append(self._flatten_record(rec, source_id=source_id))
        cursor = max(keys) if keys else since
        return LogWindow(records=tuple(records), cursor=cursor, objects_scanned=len(keys))

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _client(config: dict):
        """Assume the customer's read role and return an S3 client scoped to it."""
        from components.integrations.infrastructure.adapters.log_sources._aws_creds import (
            assume_role_client,
        )

        return assume_role_client(config, "s3")

    @staticmethod
    def _list_window_keys(s3, config: dict, *, max_objects: int, after: str = "") -> list[str]:
        """Newest ``max_objects`` object keys under the prefix. ``after`` (a cursor)
        skips already-processed keys; ``""`` reads the whole recent window."""
        prefix = config.get("prefix") or "logs/"
        keys: list[str] = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=config["bucket"], Prefix=prefix):
            for obj in page.get("Contents", []):
                if after and obj["Key"] <= after:
                    continue
                keys.append(obj["Key"])
        keys.sort()
        return keys[-max_objects:]

    @classmethod
    def _flatten_record(cls, rec: dict, *, source_id: str = "") -> LogRecord:
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
        return LogRecord(
            service=service,
            level=level,
            message=message[:1000],
            raw=inner_raw,
            ts=cls._parse_record_time(rec),
            source_kind=cls.KIND,
            source_id=source_id,
        )

    @staticmethod
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

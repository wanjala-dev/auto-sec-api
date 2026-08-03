"""EpssFeedAdapter — pulls FIRST.org's daily EPSS CSV into a dated snapshot (ADR 0013 D2).

The feed is a gzipped CSV whose first line is a ``#`` comment carrying the feed's own
version stamps (``model_version``, ``score_date``), the second line the header
(``cve,epss,percentile``), then one row per CVE. We pull over HTTPS from the authoritative
host, parse to ``EpssRecord``s, and stamp the snapshot with the feed's own ``score_date``
so scoring is reproducible against a dated pull (never a live per-request fetch).

The source URL is pinned as an explicit constant (``pin-versions.md``) — the daily CSV is
data, not a floating image tag, but the endpoint is fixed and reviewable here.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import logging
import re
from datetime import date, datetime

import httpx

from components.vuln_intel.application.ports.vuln_feed_port import EpssFeedPort
from components.vuln_intel.domain.value_objects.feed_snapshot import EpssFeedSnapshot, EpssRecord

logger = logging.getLogger(__name__)

# Pinned authoritative source (FIRST.org EPSS "current" daily CSV, gzipped).
EPSS_CURRENT_URL = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"
_HTTP_TIMEOUT = 60.0

# The metadata comment line, e.g.: ``#model_version:v2025.03.14,score_date:2026-08-03T00:00:00+0000``
_META_RE = re.compile(r"(model_version|score_date)\s*:\s*([^,]+)")


class EpssFeedAdapter(EpssFeedPort):
    def __init__(self, *, url: str = EPSS_CURRENT_URL, client: httpx.Client | None = None) -> None:
        self._url = url
        self._client = client

    def fetch(self) -> EpssFeedSnapshot:
        raw = self._download()
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
        checksum = hashlib.sha256(raw).hexdigest()
        return self._parse(text, checksum=checksum)

    def _download(self) -> bytes:
        if self._client is not None:
            resp = self._client.get(self._url)
            resp.raise_for_status()
            return resp.content
        with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(self._url)
            resp.raise_for_status()
            return resp.content

    @staticmethod
    def _parse(text: str, *, checksum: str = "") -> EpssFeedSnapshot:
        lines = text.splitlines()
        model_version = ""
        score_date: date | None = None

        # Line 1 is the ``#`` metadata comment; pull the feed's own version stamps.
        if lines and lines[0].lstrip().startswith("#"):
            meta = dict(_META_RE.findall(lines[0]))
            model_version = (meta.get("model_version") or "").strip()
            score_date = _parse_score_date(meta.get("score_date"))
            lines = lines[1:]

        records: list[EpssRecord] = []
        reader = csv.DictReader(io.StringIO("\n".join(lines)))
        for row in reader:
            cve = (row.get("cve") or "").strip()
            if not cve:
                continue
            try:
                epss = float(row.get("epss") or 0.0)
                percentile = float(row.get("percentile") or 0.0)
            except ValueError:
                logger.warning("epss_parse_skip_row cve=%s", cve)
                continue
            records.append(EpssRecord(cve=cve, epss=epss, percentile=percentile))

        # If the feed omitted a score_date comment, fall back to today (still a dated,
        # reproducible snapshot — the pull's own date).
        resolved_date = score_date or date.today()
        return EpssFeedSnapshot(
            score_date=resolved_date,
            model_version=model_version,
            records=tuple(records),
            checksum=checksum,
        )


def _parse_score_date(raw: str | None) -> date | None:
    if not raw:
        return None
    value = raw.strip()
    # Accept both a bare date and an ISO datetime with tz.
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        logger.warning("epss_score_date_unparseable value=%s", value)
        return None

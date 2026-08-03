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
import hashlib
import io
import logging
import re
from collections.abc import Iterator
from datetime import date, datetime

import httpx

from components.vuln_intel.application.ports.vuln_feed_port import EpssFeedPort
from components.vuln_intel.domain.value_objects.feed_snapshot import EpssFeedSnapshot, EpssRecord
from components.vuln_intel.infrastructure.adapters.feed_http import download_capped, gunzip_capped

logger = logging.getLogger(__name__)

# Pinned authoritative source. `epss.empiricalsecurity.com` is the current FIRST.org-linked
# Empirical Security mirror for the EPSS daily CSV (the pinned trust anchor — FIRST moved the
# canonical download here). The download + decompress are size-capped (feed_http) against an
# oversized-body / gzip-bomb (supply-chain hardening — a security tool ingesting a 3rd-party feed).
EPSS_CURRENT_URL = "https://epss.empiricalsecurity.com/epss_scores-current.csv.gz"

# The metadata comment line, e.g.: ``#model_version:v2025.03.14,score_date:2026-08-03T00:00:00+0000``
_META_RE = re.compile(r"(model_version|score_date)\s*:\s*([^,]+)")


class EpssFeedAdapter(EpssFeedPort):
    def __init__(self, *, url: str = EPSS_CURRENT_URL, client: httpx.Client | None = None) -> None:
        self._url = url
        self._client = client

    def fetch(self) -> EpssFeedSnapshot:
        raw = download_capped(self._url, client=self._client)
        text = gunzip_capped(raw).decode("utf-8", errors="replace")
        checksum = hashlib.sha256(raw).hexdigest()
        # Stream the ~280k CVEs lazily: the snapshot carries a generator over ``text``, not a
        # materialized tuple of ~280k EpssRecords. The store drains it in bounded batches so
        # the whole feed never lives in RAM at once (the old ``_parse`` tuple + bulk_create's
        # internal list together OOM-killed the 768Mi worker on the real feed).
        return self._snapshot(text, checksum=checksum)

    @classmethod
    def _snapshot(cls, text: str, *, checksum: str = "") -> EpssFeedSnapshot:
        """Build a snapshot whose ``records`` is a lazy, single-consumption stream.

        Parses the header (feed's own ``score_date`` / ``model_version``) eagerly — it's one
        line — then hands back a generator over the remaining rows. Nothing is materialized
        here; iterating ``records`` drives the CSV parse row by row.
        """
        line_iter = io.StringIO(text)
        model_version = ""
        score_date: date | None = None

        # Line 1 is the ``#`` metadata comment; pull the feed's own version stamps, leaving the
        # iterator positioned at the CSV header row. If absent, rewind so the header isn't eaten.
        first = line_iter.readline()
        if first.lstrip().startswith("#"):
            meta = dict(_META_RE.findall(first))
            model_version = (meta.get("model_version") or "").strip()
            score_date = _parse_score_date(meta.get("score_date"))
        else:
            line_iter.seek(0)

        # If the feed omitted a score_date comment, fall back to today (still a dated,
        # reproducible snapshot — the pull's own date).
        resolved_date = score_date or date.today()
        return EpssFeedSnapshot(
            score_date=resolved_date,
            model_version=model_version,
            records=cls._iter_records(line_iter),
            checksum=checksum,
        )

    @staticmethod
    def _iter_records(lines: io.StringIO) -> Iterator[EpssRecord]:
        """Yield one ``EpssRecord`` per valid CSV row from a line iterator — lazy, O(1) memory.

        ``csv.DictReader`` reads the given iterator row by row (never a full ``.read()``), so
        at most one row is held at a time. Bad rows are dropped (resilience) and values are
        clamped to [0,1] at ingest (S2)."""
        reader = csv.DictReader(lines)
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
            # Clamp to [0,1] at ingest (S2): a malformed/out-of-range feed value must never
            # reach the stored snapshot, where it would trip EpssScore's [0,1] invariant at
            # read time and break scoring. Damp defensively rather than trust the source.
            epss = min(1.0, max(0.0, epss))
            percentile = min(1.0, max(0.0, percentile))
            yield EpssRecord(cve=cve, epss=epss, percentile=percentile)

    @classmethod
    def _parse(cls, text: str, *, checksum: str = "") -> EpssFeedSnapshot:
        """Materialize a snapshot (records as a ``tuple``) — for callers that re-iterate or take
        ``len`` (unit tests, small pulls). Built on ``_snapshot`` so there is ONE parser."""
        snap = cls._snapshot(text, checksum=checksum)
        return EpssFeedSnapshot(
            score_date=snap.score_date,
            model_version=snap.model_version,
            records=tuple(snap.records),
            checksum=snap.checksum,
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

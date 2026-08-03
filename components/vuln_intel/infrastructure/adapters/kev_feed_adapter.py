"""KevFeedAdapter — pulls CISA's KEV catalog JSON into a versioned snapshot (ADR 0013 D2).

The catalog is a single JSON doc with a top-level ``catalogVersion`` and a
``vulnerabilities`` array (``cveID``, ``dateAdded``, ``knownRansomwareCampaignUse``, …).
We pull over HTTPS from the authoritative host and stamp the snapshot with the catalog's
own version so scoring is reproducible against a versioned pull.

The source URL is pinned as an explicit constant (``pin-versions.md``).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime

import httpx

from components.vuln_intel.application.ports.vuln_feed_port import KevFeedPort
from components.vuln_intel.domain.errors import MalformedFeedError
from components.vuln_intel.domain.value_objects.feed_snapshot import KevFeedSnapshot, KevRecord
from components.vuln_intel.infrastructure.adapters.feed_http import download_capped

logger = logging.getLogger(__name__)

# Pinned authoritative source (CISA KEV catalog JSON). The download is size-capped
# (feed_http) against an oversized body — supply-chain hardening for a 3rd-party feed pull.
KEV_CATALOG_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


class KevFeedAdapter(KevFeedPort):
    def __init__(self, *, url: str = KEV_CATALOG_URL, client: httpx.Client | None = None) -> None:
        self._url = url
        self._client = client

    def fetch(self) -> KevFeedSnapshot:
        raw = download_capped(self._url, client=self._client)
        checksum = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        return self._parse(data, checksum=checksum)

    @staticmethod
    def _parse(data: dict, *, checksum: str = "") -> KevFeedSnapshot:
        catalog_version = str(data.get("catalogVersion") or "").strip()
        if not catalog_version:
            # A KEV pull with no version can't be a reproducible snapshot — fail loudly
            # rather than persist an unstamped catalog.
            raise MalformedFeedError("KEV catalog missing catalogVersion")

        records: list[KevRecord] = []
        for vuln in data.get("vulnerabilities") or []:
            if not isinstance(vuln, dict):
                continue
            cve = str(vuln.get("cveID") or "").strip()
            if not cve:
                continue
            records.append(
                KevRecord(
                    cve=cve,
                    date_added=_parse_date(vuln.get("dateAdded")),
                    known_ransomware=str(vuln.get("knownRansomwareCampaignUse") or "").strip().lower() == "known",
                )
            )

        return KevFeedSnapshot(catalog_version=catalog_version, records=tuple(records), checksum=checksum)


def _parse_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(raw).strip()).date()
        except ValueError:
            return None

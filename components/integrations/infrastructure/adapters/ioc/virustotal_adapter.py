"""VirusTotal v3 enrichment adapter (implements IocEnrichmentPort).

Read-only lookups against ``https://www.virustotal.com/api/v3``. Cache-first (6h,
mirroring the Torq IOC-cache pattern) to protect the per-key rate limit. Never raises —
any failure (no key, rate limit, network, not found) returns an
``EnrichmentResult.unavailable(...)`` so a triage run degrades gracefully.

Key source (Slice 1): platform-level ``settings.VIRUSTOTAL_API_KEY`` / env var. Absent →
UNKNOWN + ``no_api_key``. Per-workspace keys via the secret envelope + a connector model
are a later slice; this adapter takes an explicit key too so that swap is a constructor
change, not a rewrite.
"""

from __future__ import annotations

import base64
import logging
import os

import requests
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables

from components.integrations.application.ports.ioc_enrichment_port import IocEnrichmentPort
from components.integrations.domain.value_objects.enrichment_result import (
    EnrichmentResult,
    EnrichmentVerdict,
)
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind

logger = logging.getLogger(__name__)

_BASE = "https://www.virustotal.com/api/v3"
_TIMEOUT = 8
_CACHE_TTL = 6 * 3600
_SUPPORTED = frozenset({IndicatorKind.IP, IndicatorKind.DOMAIN, IndicatorKind.URL, IndicatorKind.FILE_HASH})


class VirusTotalAdapter(IocEnrichmentPort):
    provider_name = "virustotal"

    @sensitive_variables("api_key")
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def supports(self) -> frozenset[IndicatorKind]:
        return _SUPPORTED

    def _key(self) -> str:
        return (
            self._api_key or getattr(settings, "VIRUSTOTAL_API_KEY", "") or os.environ.get("VIRUSTOTAL_API_KEY", "")
        ).strip()

    def _path(self, indicator: Indicator) -> str:
        if indicator.kind is IndicatorKind.IP:
            return f"/ip_addresses/{indicator.value}"
        if indicator.kind is IndicatorKind.DOMAIN:
            return f"/domains/{indicator.value}"
        if indicator.kind is IndicatorKind.FILE_HASH:
            return f"/files/{indicator.value}"
        # URL id = unpadded base64url of the URL (VT v3 convention).
        url_id = base64.urlsafe_b64encode(indicator.value.encode()).decode().strip("=")
        return f"/urls/{url_id}"

    def enrich(self, indicator: Indicator) -> EnrichmentResult:
        if indicator.kind not in _SUPPORTED:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "unsupported_kind")
        key = self._key()
        if not key:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "no_api_key")

        cache_key = f"ioc:virustotal:{indicator.kind.value}:{indicator.value}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return EnrichmentResult.from_cache_dict(cached, provider=self.provider_name, indicator=indicator)

        try:
            resp = requests.get(f"{_BASE}{self._path(indicator)}", headers={"x-apikey": key}, timeout=_TIMEOUT)
        except requests.RequestException:
            logger.exception("virustotal_request_failed kind=%s", indicator.kind.value)
            return EnrichmentResult.unavailable(self.provider_name, indicator, "request_failed")

        if resp.status_code == 404:
            result = EnrichmentResult(
                self.provider_name, indicator, EnrichmentVerdict.UNKNOWN, detail="not found in VirusTotal"
            )
        elif resp.status_code == 429:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "rate_limited")
        elif resp.status_code != 200:
            logger.warning("virustotal_http_%s kind=%s", resp.status_code, indicator.kind.value)
            return EnrichmentResult.unavailable(self.provider_name, indicator, f"http_{resp.status_code}")
        else:
            result = self._map(resp.json(), indicator)

        cache.set(cache_key, result.to_cache_dict(), _CACHE_TTL)
        return result

    def _map(self, data: dict, indicator: Indicator) -> EnrichmentResult:
        stats = (((data or {}).get("data") or {}).get("attributes") or {}).get("last_analysis_stats") or {}
        malicious = int(stats.get("malicious", 0) or 0)
        suspicious = int(stats.get("suspicious", 0) or 0)
        total = sum(int(v or 0) for v in stats.values()) or 1
        score = min(100, round((malicious * 100 + suspicious * 50) / total))
        if malicious >= 3:
            verdict = EnrichmentVerdict.MALICIOUS
        elif malicious >= 1 or suspicious >= 3:
            verdict = EnrichmentVerdict.SUSPICIOUS
        else:
            verdict = EnrichmentVerdict.BENIGN
        return EnrichmentResult(
            provider=self.provider_name,
            indicator=indicator,
            verdict=verdict,
            score=score,
            positives=malicious,
            detail=f"{malicious} malicious / {suspicious} suspicious of {total} engines",
        )

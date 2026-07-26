"""AbuseIPDB enrichment adapter (IP only) — abuse-report reputation.

Complements VirusTotal (AV engine detections) with a different signal: how many abuse
reports an IP has and the community confidence it's malicious. Cache-first, never raises
(same contract as the VirusTotal adapter). Key: ``settings.ABUSEIPDB_API_KEY`` / env.
"""

from __future__ import annotations

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

_URL = "https://api.abuseipdb.com/api/v2/check"
_TIMEOUT = 8
_CACHE_TTL = 6 * 3600
_SUPPORTED = frozenset({IndicatorKind.IP})


class AbuseIPDBAdapter(IocEnrichmentPort):
    provider_name = "abuseipdb"

    @sensitive_variables("api_key")
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def supports(self) -> frozenset[IndicatorKind]:
        return _SUPPORTED

    def _key(self) -> str:
        return (
            self._api_key or getattr(settings, "ABUSEIPDB_API_KEY", "") or os.environ.get("ABUSEIPDB_API_KEY", "")
        ).strip()

    def enrich(self, indicator: Indicator) -> EnrichmentResult:
        if indicator.kind not in _SUPPORTED:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "unsupported_kind")
        key = self._key()
        if not key:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "no_api_key")

        cache_key = f"ioc:abuseipdb:ip:{indicator.value}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return EnrichmentResult.from_cache_dict(cached, provider=self.provider_name, indicator=indicator)

        try:
            resp = requests.get(
                _URL,
                headers={"Key": key, "Accept": "application/json"},
                params={"ipAddress": indicator.value, "maxAgeInDays": 90},
                timeout=_TIMEOUT,
            )
        except requests.RequestException:
            logger.exception("abuseipdb_request_failed")
            return EnrichmentResult.unavailable(self.provider_name, indicator, "request_failed")

        if resp.status_code == 429:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "rate_limited")
        if resp.status_code != 200:
            logger.warning("abuseipdb_http_%s", resp.status_code)
            return EnrichmentResult.unavailable(self.provider_name, indicator, f"http_{resp.status_code}")

        data = (resp.json() or {}).get("data") or {}
        confidence = int(data.get("abuseConfidenceScore", 0) or 0)
        reports = int(data.get("totalReports", 0) or 0)
        if confidence >= 75:
            verdict = EnrichmentVerdict.MALICIOUS
        elif confidence >= 25:
            verdict = EnrichmentVerdict.SUSPICIOUS
        else:
            verdict = EnrichmentVerdict.BENIGN
        result = EnrichmentResult(
            provider=self.provider_name,
            indicator=indicator,
            verdict=verdict,
            score=confidence,
            positives=reports,
            detail=f"{confidence}% abuse confidence, {reports} reports",
        )
        cache.set(cache_key, result.to_cache_dict(), _CACHE_TTL)
        return result

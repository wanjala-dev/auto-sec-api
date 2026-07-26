"""GreyNoise enrichment adapter (IP only) — internet-noise classification.

The false-positive killer: GreyNoise tells you whether an IP is mass-scanning the whole
internet (benign researcher / known-good scanner, or a malicious one) vs. targeted. A
``benign`` classification is a *known-good* scanner — low threat, useful context so
triage doesn't alarm on background noise. Community v3 endpoint. Cache-first, never
raises. Key: ``settings.GREYNOISE_API_KEY`` / env.
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

_BASE = "https://api.greynoise.io/v3/community/"
_TIMEOUT = 8
_CACHE_TTL = 6 * 3600
_SUPPORTED = frozenset({IndicatorKind.IP})


class GreyNoiseAdapter(IocEnrichmentPort):
    provider_name = "greynoise"

    @sensitive_variables("api_key")
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def supports(self) -> frozenset[IndicatorKind]:
        return _SUPPORTED

    def _key(self) -> str:
        return (
            self._api_key or getattr(settings, "GREYNOISE_API_KEY", "") or os.environ.get("GREYNOISE_API_KEY", "")
        ).strip()

    def enrich(self, indicator: Indicator) -> EnrichmentResult:
        if indicator.kind not in _SUPPORTED:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "unsupported_kind")
        key = self._key()
        if not key:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "no_api_key")

        cache_key = f"ioc:greynoise:ip:{indicator.value}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return EnrichmentResult.from_cache_dict(cached, provider=self.provider_name, indicator=indicator)

        try:
            resp = requests.get(
                f"{_BASE}{indicator.value}",
                headers={"key": key, "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
        except requests.RequestException:
            logger.exception("greynoise_request_failed")
            return EnrichmentResult.unavailable(self.provider_name, indicator, "request_failed")

        if resp.status_code == 429:
            return EnrichmentResult.unavailable(self.provider_name, indicator, "rate_limited")
        if resp.status_code == 404:
            # GreyNoise has never seen this IP scanning — no signal (not "benign").
            result = EnrichmentResult(
                self.provider_name, indicator, EnrichmentVerdict.UNKNOWN, detail="no GreyNoise data"
            )
            cache.set(cache_key, result.to_cache_dict(), _CACHE_TTL)
            return result
        if resp.status_code != 200:
            logger.warning("greynoise_http_%s", resp.status_code)
            return EnrichmentResult.unavailable(self.provider_name, indicator, f"http_{resp.status_code}")

        data = resp.json() or {}
        classification = str(data.get("classification", "") or "").lower()
        noise = bool(data.get("noise"))
        name = str(data.get("name", "") or "")
        if classification == "malicious":
            verdict, score = EnrichmentVerdict.MALICIOUS, 80
        elif classification == "benign":
            verdict, score = EnrichmentVerdict.BENIGN, 5  # known-good scanner
        elif noise:
            verdict, score = EnrichmentVerdict.SUSPICIOUS, 40  # mass-scanning, intent unknown
        else:
            verdict, score = EnrichmentVerdict.UNKNOWN, 0
        detail = f"greynoise: {classification or 'unknown'}{' (noise)' if noise else ''}{' — ' + name if name else ''}"
        result = EnrichmentResult(self.provider_name, indicator, verdict, score=score, detail=detail)
        cache.set(cache_key, result.to_cache_dict(), _CACHE_TTL)
        return result

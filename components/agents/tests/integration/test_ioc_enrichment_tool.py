"""The enrich_indicator triage tool — classify + corroborate across providers (mocked)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from components.agents.infrastructure.adapters.langchain.tools.ioc_enrichment import enrich_indicator
from components.integrations.domain.value_objects.enrichment_result import (
    EnrichmentResult,
    EnrichmentVerdict,
)
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind

pytestmark = [pytest.mark.unit]

_ENRICH_ALL = "components.integrations.application.providers.ioc_enrichment_provider.IocEnrichmentProvider.enrich_all"


class _Stub:
    workspace_id = "ws-1"


def _r(provider, kind, value, verdict, **kw):
    return EnrichmentResult(provider=provider, indicator=Indicator(kind, value), verdict=verdict, **kw)


class TestEnrichIndicatorTool:
    def test_corroborates_across_sources_worst_wins(self):
        # VirusTotal malicious + GreyNoise benign-scanner → aggregate MALICIOUS, both listed.
        results = [
            _r("virustotal", IndicatorKind.IP, "8.8.8.8", EnrichmentVerdict.MALICIOUS, score=90, positives=10),
            _r("abuseipdb", IndicatorKind.IP, "8.8.8.8", EnrichmentVerdict.SUSPICIOUS, score=40, positives=5),
            _r("greynoise", IndicatorKind.IP, "8.8.8.8", EnrichmentVerdict.BENIGN, score=5),
        ]
        with mock.patch(_ENRICH_ALL, return_value=results):
            out = json.loads(enrich_indicator(_Stub(), "8.8.8.8"))
        assert out["kind"] == "ip"
        assert out["verdict"] == "malicious"  # worst real signal
        assert out["score"] == 90  # max
        assert out["sources_queried"] == 3
        assert out["sources_answered"] == 3
        assert {s["provider"] for s in out["sources"]} == {"virustotal", "abuseipdb", "greynoise"}

    def test_ignores_errored_sources_in_the_verdict(self):
        results = [
            _r("virustotal", IndicatorKind.IP, "1.2.3.4", EnrichmentVerdict.BENIGN, score=0),
            _r("abuseipdb", IndicatorKind.IP, "1.2.3.4", EnrichmentVerdict.UNKNOWN, error="no_api_key"),
        ]
        with mock.patch(_ENRICH_ALL, return_value=results):
            out = json.loads(enrich_indicator(_Stub(), "1.2.3.4"))
        assert out["verdict"] == "benign"
        assert out["sources_queried"] == 2
        assert out["sources_answered"] == 1  # the errored one doesn't count

    def test_json_wrapper_input(self):
        results = [_r("virustotal", IndicatorKind.DOMAIN, "evil.example.com", EnrichmentVerdict.SUSPICIOUS, score=50)]
        with mock.patch(_ENRICH_ALL, return_value=results):
            out = json.loads(enrich_indicator(_Stub(), '{"indicator": "evil.example.com", "provider": "virustotal"}'))
        assert out["kind"] == "domain"
        assert out["verdict"] == "suspicious"

    def test_unrecognized_indicator_fails_cleanly(self):
        out = json.loads(enrich_indicator(_Stub(), "this is not an indicator"))
        assert out["error"] == "unrecognized_indicator"

    def test_no_sources_is_unknown(self):
        with mock.patch(_ENRICH_ALL, return_value=[]):
            out = json.loads(enrich_indicator(_Stub(), "9.9.9.9"))
        assert out["verdict"] == "unknown"
        assert out["sources_answered"] == 0

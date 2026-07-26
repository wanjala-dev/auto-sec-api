"""The enrich_indicator triage tool — classify + enrich, JSON out (mocked provider)."""

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

_ENRICH = "components.integrations.application.providers.ioc_enrichment_provider.IocEnrichmentProvider.enrich"


class _Stub:
    workspace_id = "ws-1"


def _result(kind, value, verdict, **kw):
    return EnrichmentResult(provider="virustotal", indicator=Indicator(kind, value), verdict=verdict, **kw)


class TestEnrichIndicatorTool:
    def test_enriches_and_returns_verdict(self):
        fake = _result(
            IndicatorKind.IP, "8.8.8.8", EnrichmentVerdict.MALICIOUS, score=90, positives=10, detail="10 malicious"
        )
        with mock.patch(_ENRICH, return_value=fake):
            out = json.loads(enrich_indicator(_Stub(), "8.8.8.8"))
        assert out["kind"] == "ip"
        assert out["verdict"] == "malicious"
        assert out["score"] == 90
        assert out["positives"] == 10

    def test_json_wrapper_input(self):
        fake = _result(IndicatorKind.DOMAIN, "evil.example.com", EnrichmentVerdict.SUSPICIOUS, score=50)
        with mock.patch(_ENRICH, return_value=fake):
            out = json.loads(enrich_indicator(_Stub(), '{"indicator": "evil.example.com", "provider": "virustotal"}'))
        assert out["kind"] == "domain"
        assert out["verdict"] == "suspicious"

    def test_unrecognized_indicator_fails_cleanly(self):
        out = json.loads(enrich_indicator(_Stub(), "this is not an indicator"))
        assert out["error"] == "unrecognized_indicator"

    def test_hash_is_classified(self):
        fake = _result(IndicatorKind.FILE_HASH, "a" * 64, EnrichmentVerdict.UNKNOWN, detail="not found")
        with mock.patch(_ENRICH, return_value=fake):
            out = json.loads(enrich_indicator(_Stub(), "A" * 64))
        assert out["kind"] == "file_hash"

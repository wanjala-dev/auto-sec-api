"""AbuseIPDBAdapter — confidence→verdict mapping, graceful failure, cache (mocked HTTP)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.cache import cache

from components.integrations.domain.value_objects.enrichment_result import EnrichmentVerdict
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind
from components.integrations.infrastructure.adapters.ioc.abuseipdb_adapter import AbuseIPDBAdapter

pytestmark = [pytest.mark.integration]

_GET = "components.integrations.infrastructure.adapters.ioc.abuseipdb_adapter.requests.get"


def _resp(status=200, confidence=0, reports=0):
    m = mock.Mock()
    m.status_code = status
    m.json = mock.Mock(return_value={"data": {"abuseConfidenceScore": confidence, "totalReports": reports}})
    return m


def _ip(v):
    ind = Indicator(IndicatorKind.IP, v)
    cache.delete(f"ioc:abuseipdb:ip:{v}")
    return ind


class TestAbuseIPDBAdapter:
    def test_no_key_is_unavailable(self):
        r = AbuseIPDBAdapter(api_key="").enrich(_ip("8.8.8.8"))
        assert r.error == "no_api_key"

    def test_unsupported_kind(self):
        r = AbuseIPDBAdapter(api_key="k").enrich(Indicator(IndicatorKind.DOMAIN, "example.com"))
        assert r.error == "unsupported_kind"

    def test_high_confidence_is_malicious(self):
        with mock.patch(_GET, return_value=_resp(200, confidence=90, reports=42)):
            r = AbuseIPDBAdapter(api_key="k").enrich(_ip("203.0.113.1"))
        assert r.verdict is EnrichmentVerdict.MALICIOUS
        assert r.score == 90 and r.positives == 42

    def test_mid_confidence_is_suspicious(self):
        with mock.patch(_GET, return_value=_resp(200, confidence=30, reports=3)):
            r = AbuseIPDBAdapter(api_key="k").enrich(_ip("203.0.113.2"))
        assert r.verdict is EnrichmentVerdict.SUSPICIOUS

    def test_low_confidence_is_benign(self):
        with mock.patch(_GET, return_value=_resp(200, confidence=0, reports=0)):
            r = AbuseIPDBAdapter(api_key="k").enrich(_ip("203.0.113.3"))
        assert r.verdict is EnrichmentVerdict.BENIGN
        assert r.error is None

    def test_rate_limited(self):
        with mock.patch(_GET, return_value=_resp(429)):
            r = AbuseIPDBAdapter(api_key="k").enrich(_ip("203.0.113.4"))
        assert r.error == "rate_limited"

    def test_cache_hit_avoids_second_request(self):
        ind = _ip("198.51.100.1")
        with mock.patch(_GET, return_value=_resp(200, confidence=80, reports=10)) as g:
            a = AbuseIPDBAdapter(api_key="k")
            a.enrich(ind)
            a.enrich(ind)
        assert g.call_count == 1
        cache.delete(f"ioc:abuseipdb:ip:{ind.value}")

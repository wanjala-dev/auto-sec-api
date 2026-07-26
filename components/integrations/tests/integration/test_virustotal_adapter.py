"""VirusTotalAdapter — verdict mapping, graceful failure, and caching (mocked HTTP)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.cache import cache

from components.integrations.domain.value_objects.enrichment_result import EnrichmentVerdict
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind
from components.integrations.infrastructure.adapters.ioc.virustotal_adapter import VirusTotalAdapter

pytestmark = [pytest.mark.integration]

_GET = "components.integrations.infrastructure.adapters.ioc.virustotal_adapter.requests.get"


def _resp(status=200, stats=None):
    m = mock.Mock()
    m.status_code = status
    m.json = mock.Mock(return_value={"data": {"attributes": {"last_analysis_stats": stats or {}}}})
    return m


def _clear(ind):
    cache.delete(f"ioc:virustotal:{ind.kind.value}:{ind.value}")


class TestVirusTotalAdapter:
    def test_no_key_is_unavailable(self):
        r = VirusTotalAdapter(api_key="").enrich(Indicator(IndicatorKind.IP, "8.8.8.8"))
        assert r.error == "no_api_key"
        assert r.verdict is EnrichmentVerdict.UNKNOWN

    def test_unsupported_kind_is_unavailable(self):
        # Force an unsupported kind by faking one (adapter must not crash).
        ind = Indicator(IndicatorKind.IP, "8.8.8.8")
        object.__setattr__(ind, "kind", "email")  # not in _SUPPORTED
        r = VirusTotalAdapter(api_key="k").enrich(ind)
        assert r.error == "unsupported_kind"

    def test_malicious_mapping(self):
        ind = Indicator(IndicatorKind.FILE_HASH, "a" * 64)
        _clear(ind)
        with mock.patch(
            _GET, return_value=_resp(200, {"malicious": 10, "suspicious": 2, "harmless": 50, "undetected": 8})
        ) as g:
            r = VirusTotalAdapter(api_key="k").enrich(ind)
        assert r.verdict is EnrichmentVerdict.MALICIOUS
        assert r.positives == 10
        assert 0 < r.score <= 100
        assert g.call_count == 1

    def test_benign_mapping(self):
        ind = Indicator(IndicatorKind.DOMAIN, "benign-xyz-example.com")
        _clear(ind)
        with mock.patch(
            _GET, return_value=_resp(200, {"malicious": 0, "suspicious": 0, "harmless": 80, "undetected": 5})
        ):
            r = VirusTotalAdapter(api_key="k").enrich(ind)
        assert r.verdict is EnrichmentVerdict.BENIGN
        assert r.error is None

    def test_404_is_unknown_not_error(self):
        ind = Indicator(IndicatorKind.IP, "203.0.113.7")
        _clear(ind)
        with mock.patch(_GET, return_value=_resp(404)):
            r = VirusTotalAdapter(api_key="k").enrich(ind)
        assert r.verdict is EnrichmentVerdict.UNKNOWN
        assert r.error is None  # "not found" is a real answer, not a failure

    def test_rate_limited_is_unavailable(self):
        ind = Indicator(IndicatorKind.IP, "203.0.113.8")
        _clear(ind)
        with mock.patch(_GET, return_value=_resp(429)):
            r = VirusTotalAdapter(api_key="k").enrich(ind)
        assert r.error == "rate_limited"

    def test_network_error_is_unavailable(self):
        import requests

        ind = Indicator(IndicatorKind.IP, "203.0.113.9")
        _clear(ind)
        with mock.patch(_GET, side_effect=requests.RequestException("boom")):
            r = VirusTotalAdapter(api_key="k").enrich(ind)
        assert r.error == "request_failed"
        assert r.verdict is EnrichmentVerdict.UNKNOWN

    def test_cache_hit_avoids_second_request(self):
        ind = Indicator(IndicatorKind.IP, "198.51.100.9")
        _clear(ind)
        with mock.patch(_GET, return_value=_resp(200, {"malicious": 5, "harmless": 40})) as g:
            adapter = VirusTotalAdapter(api_key="k")
            r1 = adapter.enrich(ind)
            r2 = adapter.enrich(ind)
        assert g.call_count == 1  # second lookup served from cache
        assert r1.verdict is r2.verdict
        _clear(ind)

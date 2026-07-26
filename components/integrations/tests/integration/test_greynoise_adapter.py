"""GreyNoiseAdapter — classification→verdict mapping + graceful failure (mocked HTTP)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.cache import cache

from components.integrations.domain.value_objects.enrichment_result import EnrichmentVerdict
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind
from components.integrations.infrastructure.adapters.ioc.greynoise_adapter import GreyNoiseAdapter

pytestmark = [pytest.mark.integration]

_GET = "components.integrations.infrastructure.adapters.ioc.greynoise_adapter.requests.get"


def _resp(status=200, classification="", noise=False, name=""):
    m = mock.Mock()
    m.status_code = status
    m.json = mock.Mock(return_value={"classification": classification, "noise": noise, "name": name})
    return m


def _ip(v):
    ind = Indicator(IndicatorKind.IP, v)
    cache.delete(f"ioc:greynoise:ip:{v}")
    return ind


class TestGreyNoiseAdapter:
    def test_no_key_is_unavailable(self):
        assert GreyNoiseAdapter(api_key="").enrich(_ip("8.8.8.8")).error == "no_api_key"

    def test_unsupported_kind(self):
        r = GreyNoiseAdapter(api_key="k").enrich(Indicator(IndicatorKind.FILE_HASH, "a" * 64))
        assert r.error == "unsupported_kind"

    def test_malicious_classification(self):
        with mock.patch(_GET, return_value=_resp(200, classification="malicious", noise=True, name="Bad Scanner")):
            r = GreyNoiseAdapter(api_key="k").enrich(_ip("203.0.113.10"))
        assert r.verdict is EnrichmentVerdict.MALICIOUS

    def test_benign_scanner_is_benign_low_score(self):
        with mock.patch(_GET, return_value=_resp(200, classification="benign", noise=True, name="Shodan")):
            r = GreyNoiseAdapter(api_key="k").enrich(_ip("203.0.113.11"))
        assert r.verdict is EnrichmentVerdict.BENIGN
        assert r.score == 5  # known-good scanner: low threat

    def test_noise_without_classification_is_suspicious(self):
        with mock.patch(_GET, return_value=_resp(200, classification="", noise=True)):
            r = GreyNoiseAdapter(api_key="k").enrich(_ip("203.0.113.12"))
        assert r.verdict is EnrichmentVerdict.SUSPICIOUS

    def test_404_is_unknown_not_error(self):
        with mock.patch(_GET, return_value=_resp(404)):
            r = GreyNoiseAdapter(api_key="k").enrich(_ip("203.0.113.13"))
        assert r.verdict is EnrichmentVerdict.UNKNOWN
        assert r.error is None

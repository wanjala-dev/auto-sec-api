"""Unit tests for cross-provider corroboration (worst real signal wins)."""

from __future__ import annotations

import pytest

from components.integrations.domain.value_objects.enrichment_result import (
    EnrichmentResult,
    EnrichmentVerdict,
    corroborate,
)
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind

pytestmark = [pytest.mark.unit]

_IND = Indicator(IndicatorKind.IP, "8.8.8.8")


def _r(provider, verdict, score=0, error=None):
    return EnrichmentResult(provider=provider, indicator=_IND, verdict=verdict, score=score, error=error)


class TestCorroborate:
    def test_worst_verdict_and_max_score_win(self):
        agg = corroborate(
            _IND,
            [
                _r("greynoise", EnrichmentVerdict.BENIGN, 5),
                _r("virustotal", EnrichmentVerdict.MALICIOUS, 90),
                _r("abuseipdb", EnrichmentVerdict.SUSPICIOUS, 40),
            ],
        )
        assert agg.verdict is EnrichmentVerdict.MALICIOUS
        assert agg.score == 90
        assert set(agg.sources) == {"greynoise", "virustotal", "abuseipdb"}

    def test_errored_sources_are_excluded(self):
        agg = corroborate(
            _IND,
            [
                _r("virustotal", EnrichmentVerdict.BENIGN, 0),
                _r("abuseipdb", EnrichmentVerdict.UNKNOWN, error="no_api_key"),
            ],
        )
        assert agg.verdict is EnrichmentVerdict.BENIGN
        assert agg.sources == ["virustotal"]  # the errored provider doesn't count

    def test_all_errored_is_unknown(self):
        agg = corroborate(
            _IND,
            [
                _r("virustotal", EnrichmentVerdict.UNKNOWN, error="request_failed"),
                _r("abuseipdb", EnrichmentVerdict.UNKNOWN, error="rate_limited"),
            ],
        )
        assert agg.verdict is EnrichmentVerdict.UNKNOWN
        assert agg.sources == []

    def test_empty_is_unknown(self):
        agg = corroborate(_IND, [])
        assert agg.verdict is EnrichmentVerdict.UNKNOWN
        assert agg.score == 0

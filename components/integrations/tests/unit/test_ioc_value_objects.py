"""Unit tests for the IOC value objects (no DB, no network)."""

from __future__ import annotations

import pytest

from components.integrations.domain.value_objects.enrichment_result import (
    EnrichmentResult,
    EnrichmentVerdict,
)
from components.integrations.domain.value_objects.indicator import Indicator, IndicatorKind

pytestmark = [pytest.mark.unit]


class TestIndicatorDetect:
    @pytest.mark.parametrize(
        "raw,kind",
        [
            ("8.8.8.8", IndicatorKind.IP),
            ("2001:db8::1", IndicatorKind.IP),
            ("a" * 64, IndicatorKind.FILE_HASH),
            ("d41d8cd98f00b204e9800998ecf8427e", IndicatorKind.FILE_HASH),
            ("https://evil.example.com/x", IndicatorKind.URL),
            ("evil.example.com", IndicatorKind.DOMAIN),
            ("sub.domain-1.co.uk", IndicatorKind.DOMAIN),
        ],
    )
    def test_detects_kind(self, raw, kind):
        ind = Indicator.detect(raw)
        assert ind is not None and ind.kind is kind

    @pytest.mark.parametrize("raw", ["", "  ", "not an ioc", "hello world", "justtext"])
    def test_non_indicators_return_none(self, raw):
        assert Indicator.detect(raw) is None

    def test_strips_quotes(self):
        assert Indicator.detect('"8.8.8.8"').value == "8.8.8.8"

    def test_empty_value_rejected(self):
        with pytest.raises(ValueError):
            Indicator(IndicatorKind.IP, "   ")


class TestEnrichmentResult:
    def test_unavailable_is_unknown_with_error(self):
        r = EnrichmentResult.unavailable("virustotal", Indicator(IndicatorKind.IP, "1.1.1.1"), "no_api_key")
        assert r.verdict is EnrichmentVerdict.UNKNOWN
        assert r.error == "no_api_key"
        assert r.is_actionable is False

    def test_malicious_is_actionable(self):
        r = EnrichmentResult(
            "virustotal", Indicator(IndicatorKind.IP, "1.1.1.1"), EnrichmentVerdict.MALICIOUS, score=90
        )
        assert r.is_actionable is True

    def test_benign_is_not_actionable(self):
        r = EnrichmentResult("virustotal", Indicator(IndicatorKind.IP, "1.1.1.1"), EnrichmentVerdict.BENIGN)
        assert r.is_actionable is False

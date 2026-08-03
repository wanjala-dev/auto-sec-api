"""Unit tests for the pure contextual-risk scorer (ADR 0013 D1) — no DB, no I/O."""

from __future__ import annotations

import pytest

from components.findings.domain.services.contextual_risk_scorer import (
    extract_cve,
    score_finding,
)
from components.shared_kernel.domain.security import RiskBand, Severity

pytestmark = pytest.mark.unit


class TestKevDominance:
    def test_kev_floors_a_low_blend_finding_to_red(self):
        # A private, low-EPSS, medium finding would band GREEN/AMBER — KEV forces RED.
        result = score_finding(
            severity=Severity.MEDIUM,
            cvss_base=5.0,
            has_cve=True,
            epss=0.01,
            epss_percentile=0.2,
            in_kev=True,
            exposure="private",
        )
        assert result.in_kev is True
        assert result.band == RiskBand.RED.value
        assert result.value >= 67.0
        assert any(f.key == "kev" for f in result.factors)

    def test_non_kev_equivalent_is_not_red(self):
        result = score_finding(
            severity=Severity.MEDIUM,
            cvss_base=5.0,
            has_cve=True,
            epss=0.01,
            epss_percentile=0.2,
            in_kev=False,
            exposure="private",
        )
        assert result.band != RiskBand.RED.value


class TestEpssGate:
    def test_epss_collapses_critical_but_unlikely_below_likely_medium(self):
        # CVSS 9.8 but EPSS 0.0002 (unlikely) ...
        critical_unlikely = score_finding(
            severity=Severity.CRITICAL,
            cvss_base=9.8,
            has_cve=True,
            epss=0.0002,
            epss_percentile=0.05,
            in_kev=False,
            exposure="public",
        )
        # ... vs CVSS 6.5 with EPSS 0.86 (likely) on the same public asset.
        medium_likely = score_finding(
            severity=Severity.MEDIUM,
            cvss_base=6.5,
            has_cve=True,
            epss=0.86,
            epss_percentile=0.95,
            in_kev=False,
            exposure="public",
        )
        assert medium_likely.value > critical_unlikely.value

    def test_epss_gate_never_zeroes_a_real_finding(self):
        result = score_finding(
            severity=Severity.HIGH,
            cvss_base=8.1,
            has_cve=True,
            epss=0.0,
            epss_percentile=0.0,
            in_kev=False,
            exposure="public",
        )
        assert result.value > 0.0  # the 0.3 floor keeps impact from zeroing


class TestExposureAmplifier:
    def _score(self, exposure):
        return score_finding(
            severity=Severity.HIGH,
            cvss_base=8.0,
            has_cve=True,
            epss=0.5,
            epss_percentile=0.8,
            in_kev=False,
            exposure=exposure,
        ).value

    def test_public_outranks_internal_outranks_private(self):
        assert self._score("public") > self._score("internal") > self._score("private")


class TestUnknownExposure:
    def test_unknown_exposure_is_flagged_and_treated_as_private(self):
        unknown = score_finding(
            severity=Severity.HIGH,
            cvss_base=8.0,
            has_cve=True,
            epss=0.5,
            epss_percentile=0.8,
            in_kev=False,
            exposure=None,
        )
        private = score_finding(
            severity=Severity.HIGH,
            cvss_base=8.0,
            has_cve=True,
            epss=0.5,
            epss_percentile=0.8,
            in_kev=False,
            exposure="private",
        )
        assert unknown.exposure_unknown is True
        assert unknown.exposure == "private"
        assert unknown.value == private.value  # damped to the private amplifier
        assert any("unknown" in f.detail for f in unknown.factors)


class TestNonCveDegradation:
    def test_misconfig_without_cve_still_scores_and_respects_exposure(self):
        public = score_finding(
            severity=Severity.HIGH,
            cvss_base=None,
            has_cve=False,
            epss=None,
            epss_percentile=None,
            in_kev=False,
            exposure="public",
        )
        private = score_finding(
            severity=Severity.HIGH,
            cvss_base=None,
            has_cve=False,
            epss=None,
            epss_percentile=None,
            in_kev=False,
            exposure="private",
        )
        assert public.value > 0.0
        assert public.value > private.value  # public misconfig outranks the private one
        assert public.epss is None
        assert any("severity prior" in f.detail for f in public.factors)

    def test_cvss_base_used_over_severity_when_present(self):
        with_cvss = score_finding(
            severity=Severity.LOW,  # severity says low ...
            cvss_base=9.8,  # ... but the real CVSS base is critical
            has_cve=True,
            epss=0.5,
            epss_percentile=0.8,
            in_kev=False,
            exposure="public",
        )
        assert any("CVSS 9.8" in f.detail for f in with_cvss.factors)


class TestExtractCve:
    def test_reads_vulnerability_id(self):
        assert extract_cve({"vulnerability_id": "CVE-2021-44228"}) == "CVE-2021-44228"

    def test_ghsa_only_advisory_has_no_cve(self):
        assert extract_cve({"vulnerability_id": "GHSA-xxxx-yyyy-zzzz"}) is None

    def test_no_cve_returns_none(self):
        assert extract_cve({}) is None
        assert extract_cve({"check_id": "s3-public"}) is None

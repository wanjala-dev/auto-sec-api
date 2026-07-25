"""Unit tests for the shared CNAPP security value objects (ADR 0004 Phase 1).

These types are the cross-pillar vocabulary — if their ordering, OCSF mapping, or
identity validation drifts, every scanner and lens that speaks them drifts with it.
"""

from __future__ import annotations

import pytest

from components.shared_kernel.domain.security import (
    AssetUrn,
    FindingStatus,
    RiskBand,
    Severity,
)


@pytest.mark.unit
class TestSeverity:
    def test_orders_informational_to_critical(self):
        assert Severity.INFORMATIONAL < Severity.LOW < Severity.MEDIUM < Severity.HIGH < Severity.CRITICAL

    def test_max_of_a_set_is_the_worst(self):
        assert max({Severity.LOW, Severity.CRITICAL, Severity.MEDIUM}) is Severity.CRITICAL

    def test_comparison_with_non_severity_is_not_implemented(self):
        with pytest.raises(TypeError):
            _ = Severity.HIGH < 3  # type: ignore[operator]

    def test_from_name_canonical_and_aliases(self):
        assert Severity.from_name("critical") is Severity.CRITICAL
        assert Severity.from_name("  HIGH ") is Severity.HIGH
        assert Severity.from_name("info") is Severity.INFORMATIONAL
        assert Severity.from_name("moderate") is Severity.MEDIUM
        assert Severity.from_name("crit") is Severity.CRITICAL

    def test_from_name_rejects_unknown(self):
        with pytest.raises(ValueError):
            Severity.from_name("catastrophic")

    def test_from_ocsf_id_maps_bands(self):
        assert Severity.from_ocsf_id(1) is Severity.INFORMATIONAL
        assert Severity.from_ocsf_id(2) is Severity.LOW
        assert Severity.from_ocsf_id(3) is Severity.MEDIUM
        assert Severity.from_ocsf_id(4) is Severity.HIGH
        assert Severity.from_ocsf_id(5) is Severity.CRITICAL
        assert Severity.from_ocsf_id(6) is Severity.CRITICAL  # OCSF Fatal → top band

    def test_from_ocsf_unknown_does_not_manufacture_urgency(self):
        assert Severity.from_ocsf_id(0) is Severity.INFORMATIONAL
        assert Severity.from_ocsf_id(99) is Severity.INFORMATIONAL


@pytest.mark.unit
class TestFindingStatus:
    def test_terminal_states(self):
        assert FindingStatus.RESOLVED.is_terminal
        assert FindingStatus.SUPPRESSED.is_terminal
        assert not FindingStatus.OPEN.is_terminal
        assert not FindingStatus.TRIAGED.is_terminal

    def test_from_ocsf_id(self):
        assert FindingStatus.from_ocsf_id(1) is FindingStatus.OPEN
        assert FindingStatus.from_ocsf_id(2) is FindingStatus.TRIAGED
        assert FindingStatus.from_ocsf_id(3) is FindingStatus.SUPPRESSED
        assert FindingStatus.from_ocsf_id(4) is FindingStatus.RESOLVED

    def test_from_ocsf_unknown_is_open_not_closed(self):
        assert FindingStatus.from_ocsf_id(0) is FindingStatus.OPEN
        assert FindingStatus.from_ocsf_id(99) is FindingStatus.OPEN


@pytest.mark.unit
class TestRiskBand:
    def test_from_score_bands(self):
        assert RiskBand.from_score(90) is RiskBand.RED
        assert RiskBand.from_score(67) is RiskBand.RED
        assert RiskBand.from_score(50) is RiskBand.AMBER
        assert RiskBand.from_score(34) is RiskBand.AMBER
        assert RiskBand.from_score(10) is RiskBand.GREEN
        assert RiskBand.from_score(0) is RiskBand.GREEN

    def test_from_score_clamps_out_of_range(self):
        assert RiskBand.from_score(1000) is RiskBand.RED
        assert RiskBand.from_score(-5) is RiskBand.GREEN


@pytest.mark.unit
class TestAssetUrn:
    def test_wraps_and_strips_value(self):
        urn = AssetUrn("  arn:aws:s3:::my-bucket  ")
        assert urn.value == "arn:aws:s3:::my-bucket"
        assert str(urn) == "arn:aws:s3:::my-bucket"

    def test_empty_is_rejected(self):
        with pytest.raises(ValueError):
            AssetUrn("")
        with pytest.raises(ValueError):
            AssetUrn("   ")

    def test_is_frozen_and_hashable(self):
        urn = AssetUrn("arn:aws:iam::123456789012:role/admin")
        with pytest.raises(Exception):
            urn.value = "other"  # type: ignore[misc]
        # usable as a dict/set key (correlation by identity)
        assert {urn: 1}[AssetUrn("arn:aws:iam::123456789012:role/admin")] == 1

    def test_provider_parsing(self):
        assert AssetUrn("arn:aws:s3:::b").provider == "aws"
        assert AssetUrn("urn:gcp:storage:my-bucket").provider == "gcp"
        assert AssetUrn("some-opaque-id").provider == "unknown"

    def test_from_aws_arn(self):
        urn = AssetUrn.from_aws_arn("arn:aws:ec2:us-east-1:123:instance/i-abc")
        assert urn.provider == "aws"
        with pytest.raises(ValueError):
            AssetUrn.from_aws_arn("not-an-arn")

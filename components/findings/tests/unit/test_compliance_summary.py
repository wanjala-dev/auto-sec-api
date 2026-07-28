"""Unit tests for the compliance posture summary (pure + use case)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.findings.application.use_cases.get_compliance_summary_use_case import (
    GetComplianceSummaryUseCase,
)
from components.findings.domain.services.compliance_summary import build

pytestmark = pytest.mark.unit


def test_buckets_versioned_keys_by_family_and_dedups_controls():
    bags = [
        {"CIS-2.0": ["2.1.5", "1.4"], "PCI-4.0": ["7.2.1"]},
        # CIS-1.4 shares control "2.1.5" → counted once in the CIS family
        {"CIS-1.4": ["2.1.5", "3.1"], "SOC2": ["CC6.1"]},
    ]
    summary = build(bags)
    by_name = {f.name: f.failing_controls for f in summary.frameworks}
    assert by_name["CIS AWS"] == 3  # {2.1.5, 1.4, 3.1}
    assert by_name["PCI-DSS"] == 1
    assert by_name["SOC 2"] == 1
    assert summary.frameworks_with_failures == 3
    assert summary.total_failing_controls == 5
    # the per-framework control sample is carried (sorted, deduped) for the drill-down
    cis = next(f for f in summary.frameworks if f.name == "CIS AWS")
    assert cis.controls == ("1.4", "2.1.5", "3.1")


def test_controls_sample_is_capped_and_sorted():
    from components.findings.domain.services.compliance_summary import _CONTROLS_SAMPLE

    bags = [{"PCI-4.0": [f"ctrl-{i:03d}" for i in range(100)]}]
    summary = build(bags)
    pci = next(f for f in summary.frameworks if f.name == "PCI-DSS")
    assert pci.failing_controls == 100  # true total preserved
    assert len(pci.controls) == _CONTROLS_SAMPLE  # sample capped
    assert list(pci.controls) == sorted(pci.controls)  # sorted


def test_sorted_worst_first_and_ignores_unknown_frameworks():
    bags = [
        {"CIS-2.0": ["a", "b", "c"], "SomeVendorFramework-9": ["x", "y"]},
        {"HIPAA": ["164.312"]},
    ]
    summary = build(bags)
    names = [f.name for f in summary.frameworks]
    assert names[0] == "CIS AWS"  # 3 controls, worst → first
    assert "HIPAA" in names
    # a non-curated framework is not surfaced
    assert all("SomeVendor" not in n for n in names)


def test_empty_and_missing_bags():
    summary = build([{}, None, {"NotCurated": ["z"]}])
    assert summary.frameworks == ()
    assert summary.frameworks_with_failures == 0
    assert summary.total_failing_controls == 0


class _FakeFindingStore:
    def __init__(self, bags):
        self._bags = bags
        self.calls = 0

    def open_finding_compliance(self, workspace_id):
        self.calls += 1
        return self._bags


def test_use_case_reads_and_builds():
    store = _FakeFindingStore([{"CIS-3.0": ["1.1", "1.2"]}, {"PCI-4.0": ["8.3.1"]}])
    summary = GetComplianceSummaryUseCase(finding_store=store).execute(uuid4())
    assert store.calls == 1
    by_name = {f.name: f.failing_controls for f in summary.frameworks}
    assert by_name == {"CIS AWS": 2, "PCI-DSS": 1}
    assert summary.total_failing_controls == 3

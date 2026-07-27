"""Pure aggregation tests for the ATT&CK coverage heatmap builder."""

from __future__ import annotations

import pytest

from components.findings.domain.services.attck_coverage_builder import build_attck_coverage

pytestmark = pytest.mark.unit


def test_empty_input_yields_empty_heatmap():
    cov = build_attck_coverage([])
    assert cov["tactics"] == []
    assert cov["totals"] == {"techniques": 0, "findings": 0, "tactics": 0}


def test_groups_by_tactic_in_kill_chain_order():
    entries = [
        (["T1190", "T1078.004"], "high"),  # Initial Access + Priv-Esc
        (["T1530"], "critical"),  # Collection
    ]
    cov = build_attck_coverage(entries)
    tactics = [t["tactic"] for t in cov["tactics"]]
    assert tactics == ["initial_access", "privilege_escalation", "collection"]  # kill-chain order


def test_counts_and_worst_severity_per_technique():
    entries = [
        (["T1190"], "low"),
        (["T1190"], "critical"),
        (["T1190"], "medium"),
    ]
    cov = build_attck_coverage(entries)
    ia = next(t for t in cov["tactics"] if t["tactic"] == "initial_access")
    tech = ia["techniques"][0]
    assert tech["technique_id"] == "T1190"
    assert tech["finding_count"] == 3
    assert tech["max_severity"] == "critical"
    assert cov["totals"] == {"techniques": 1, "findings": 3, "tactics": 1}


def test_unknown_technique_ids_are_skipped():
    entries = [(["T9999", "T1190"], "high"), (["T9999"], "high")]
    cov = build_attck_coverage(entries)
    # T9999 is not in the catalogue; only T1190 counts, and the second finding
    # (only T9999) does not contribute at all.
    assert cov["totals"]["techniques"] == 1
    assert cov["totals"]["findings"] == 1


def test_techniques_within_tactic_sorted_by_count_desc():
    entries = [
        (["T1078.004"], "high"),
        (["T1078.004"], "high"),
        (["T1098.003"], "high"),
    ]
    cov = build_attck_coverage(entries)
    priv = next(t for t in cov["tactics"] if t["tactic"] == "privilege_escalation")
    ids = [t["technique_id"] for t in priv["techniques"]]
    assert ids == ["T1078.004", "T1098.003"]  # 2 findings before 1

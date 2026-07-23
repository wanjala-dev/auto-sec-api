"""Unit tests for the deterministic report assembler + section builder.

Pure — no DB, no LLM. The finding source is an in-memory fake (one fake per
port, per the testing skill). These lock the deliverable-shaping contract:
histogram counts, FID-by-severity ordering, CVSS-indicative mapping, evidence
rendering from the real payload shape, and no-findings honesty.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import pytest

from components.report.application.services.report_assembler_service import (
    AssembleScope,
    ReportAssemblerService,
)
from components.report.domain.report_kind import UnknownReportKind
from components.report.domain.value_objects.severity import Severity

pytestmark = pytest.mark.unit


class FakeFindingSource:
    """In-memory ``FindingSourcePort`` — returns the findings it was seeded with,
    honouring the source_types / prefix filters so scope tests are real."""

    def __init__(self, findings: list[Mapping[str, Any]]) -> None:
        self._findings = findings
        self.last_call: dict[str, Any] | None = None

    def list_findings(
        self,
        *,
        workspace_id: str,
        source_type_prefixes: Sequence[str],
        source_types: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> list[Mapping[str, Any]]:
        self.last_call = {
            "workspace_id": workspace_id,
            "source_type_prefixes": tuple(source_type_prefixes),
            "source_types": tuple(source_types) if source_types else None,
            "since": since,
            "until": until,
            "limit": limit,
        }
        out = [
            f for f in self._findings if any(str(f.get("source_type", "")).startswith(p) for p in source_type_prefixes)
        ]
        if source_types:
            out = [f for f in out if f.get("source_type") in set(source_types)]
        return out[:limit]


def _finding(
    *,
    fid_hint: str,
    severity: str,
    title: str,
    service: str = "auth-svc",
    source_type: str = "ai.log_watch.error",
    action_type: str = "log_watch.error",
    signal: str = "Repeated auth failures",
    recommendation: str = "Rotate the affected credentials.",
    evidence: list | None = None,
) -> dict[str, Any]:
    return {
        "id": f"task-{fid_hint}",
        "title": title,
        "description": "",
        "source_type": source_type,
        "status": "todo",
        "created_at": datetime(2026, 7, 20, 12, 0, 0),
        "metadata": {
            "severity": severity,
            "action_type": action_type,
            "detector": "logwatch",
            "ai_headline": title,
            "ai_narrative": f"Detector narrative for {title}.",
            "payload": {
                "signal": signal,
                "service": service,
                "level": "ERROR",
                "evidence": evidence if evidence is not None else [{"type": "log_line", "detail": "500 auth error"}],
                "blast_radius": {"service": service, "level": "ERROR", "window_records": 42},
                "confidence": "high",
                "recommendation": recommendation,
            },
        },
    }


def _assemble(findings: list[Mapping[str, Any]], **scope_kwargs):
    source = FakeFindingSource(findings)
    service = ReportAssemblerService(source)
    scope = AssembleScope(workspace_id="ws-1", **scope_kwargs)
    return service.assemble(scope), source


class TestHistogram:
    def test_counts_per_band(self):
        findings = [
            _finding(fid_hint="1", severity="high", title="High A"),
            _finding(fid_hint="2", severity="high", title="High B"),
            _finding(fid_hint="3", severity="medium", title="Medium A"),
            _finding(fid_hint="4", severity="low", title="Low A"),
            _finding(fid_hint="5", severity="critical", title="Crit A"),
        ]
        report, _ = _assemble(findings)
        assert report.histogram.counts == {"critical": 1, "high": 2, "medium": 1, "low": 1}
        assert report.histogram.total == 5
        assert report.histogram.highest_band == "critical"

    def test_unknown_severity_normalises_to_low(self):
        findings = [_finding(fid_hint="1", severity="bogus", title="Weird")]
        report, _ = _assemble(findings)
        assert report.histogram.counts["low"] == 1


class TestFidOrdering:
    def test_most_severe_gets_f01(self):
        findings = [
            _finding(fid_hint="low", severity="low", title="Low thing"),
            _finding(fid_hint="crit", severity="critical", title="Critical thing"),
            _finding(fid_hint="med", severity="medium", title="Medium thing"),
        ]
        report, _ = _assemble(findings)
        assert report.matrix[0].fid == "F-01"
        assert report.matrix[0].severity.band == "critical"
        assert report.matrix[-1].severity.band == "low"
        # FIDs are contiguous and unique.
        assert [r.fid for r in report.matrix] == ["F-01", "F-02", "F-03"]


class TestCvssIndicative:
    def test_band_maps_to_indicative_cvss(self):
        assert Severity("critical").cvss == 9.5
        assert Severity("high").cvss == 8.0
        assert Severity("medium").cvss == 5.5
        assert Severity("low").cvss == 2.5

    def test_technical_finding_carries_indicative_cvss(self):
        findings = [_finding(fid_hint="1", severity="high", title="H")]
        report, _ = _assemble(findings)
        assert report.technical_findings[0].cvss == 8.0


class TestEvidenceRender:
    def test_evidence_block_pulls_payload_lines(self):
        findings = [
            _finding(
                fid_hint="1",
                severity="high",
                title="Evidence finding",
                service="payments-api",
                evidence=[{"type": "log_line", "detail": "HTTP 500 from /charge"}],
            )
        ]
        report, _ = _assemble(findings)
        block = report.technical_findings[0].evidence
        joined = "\n".join(block.lines)
        assert "payments-api" in joined
        assert "HTTP 500 from /charge" in joined
        assert "confidence: high" in block.caption

    def test_remediation_falls_back_when_absent(self):
        findings = [_finding(fid_hint="1", severity="low", title="No fix", recommendation="")]
        report, _ = _assemble(findings)
        rem = report.technical_findings[0].remediation
        assert len(rem) == 1
        assert "No automated remediation" in rem[0]


class TestNoFindingsHonesty:
    def test_empty_board_produces_empty_but_valid_report(self):
        report, _ = _assemble([])
        assert report.finding_count == 0
        assert report.histogram.total == 0
        assert report.histogram.highest_band is None
        assert report.matrix == ()
        assert report.technical_findings == ()
        # Grounding still carries the honest zero counts.
        assert any("Total findings: 0" in t for t in report.grounding_texts)


class TestGroundingCorpus:
    def test_grounding_includes_every_finding_fact(self):
        findings = [_finding(fid_hint="1", severity="high", title="Groundable finding", service="auth-svc")]
        report, _ = _assemble(findings)
        corpus = " ".join(report.grounding_texts)
        assert "Groundable finding" in corpus
        assert "auth-svc" in corpus
        assert "High severity findings: 1" in corpus


class TestScopeFilters:
    def test_source_types_filter_narrows(self):
        findings = [
            _finding(fid_hint="1", severity="high", title="Log", source_type="ai.log_watch.error"),
            _finding(fid_hint="2", severity="high", title="Opt", source_type="ai.log_optimization.volume"),
        ]
        report, source = _assemble(findings, source_types=["ai.log_watch.error"])
        assert report.finding_count == 1
        assert report.technical_findings[0].title == "Log"
        assert source.last_call["source_types"] == ("ai.log_watch.error",)

    def test_unknown_kind_raises(self):
        source = FakeFindingSource([])
        service = ReportAssemblerService(source)
        with pytest.raises(UnknownReportKind):
            service.assemble(AssembleScope(workspace_id="ws-1", kind="nope"))

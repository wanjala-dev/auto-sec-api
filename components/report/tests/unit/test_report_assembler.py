"""Unit tests for the deterministic report assembler + section builder.

Pure — no DB, no LLM. The finding source is an in-memory fake (one fake per
port, per the testing skill). These lock the deliverable-shaping contract:
histogram counts, FID-by-severity ordering, CVSS-indicative mapping, evidence
rendering from the real payload shape, and no-findings honesty.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pytest

from components.report.application.ports.finding_source_port import FindingPage, FindingQuery
from components.report.application.services.report_assembler_service import (
    AssembleScope,
    ReportAssemblerService,
)
from components.report.domain.report_kind import UnknownReportKind
from components.report.domain.value_objects.severity import Severity

pytestmark = pytest.mark.unit


class FakeFindingSource:
    """In-memory ``FindingSourcePort`` — returns the findings it was seeded with,
    honouring the source allow-list so scope tests are real, and reporting the
    truncation accounting the way a real adapter must."""

    def __init__(self, findings: list[Mapping[str, Any]], *, extra_matched: int = 0) -> None:
        self._findings = findings
        self._extra_matched = extra_matched  # matched-but-not-returned (truncation)
        self.last_query: FindingQuery | None = None

    def list_findings(self, query: FindingQuery) -> FindingPage:
        self.last_query = query
        out = list(self._findings)
        if query.source_prefixes:
            out = [f for f in out if any(str(f.get("source", "")).startswith(p) for p in query.source_prefixes)]
        if query.sources:
            out = [f for f in out if any(str(f.get("source", "")).startswith(p) for p in query.sources)]
        returned = out[: query.limit]
        return FindingPage(
            findings=tuple(returned),
            total_matched=len(out) + self._extra_matched,
            sample_count=sum(1 for f in returned if f.get("is_sample")),
        )


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
    source: str | None = None,
    dedup_key: str | None = None,
    on_board: bool = True,
    is_sample: bool = False,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": f"task-{fid_hint}",
        "title": title,
        "description": "",
        # ``severity`` is first-class on the port's mapping now.
        "severity": severity,
        "source": source if source is not None else source_type,
        "source_type": source_type,
        "status": "open",
        "created_at": datetime(2026, 7, 20, 12, 0, 0),
        "is_sample": is_sample,
        "triage": (
            {
                "on_board": True,
                "column": "Todo",
                "team": "AI Findings",
                "task_status": "todo",
                "triage_status": "pending",
                "assignees": ["alice"],
            }
            if on_board
            else {"on_board": False}
        ),
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
    if dedup_key:
        finding["dedup_key"] = dedup_key
    return finding


def _assemble(findings: list[Mapping[str, Any]], **scope_kwargs):
    source = FakeFindingSource(findings)
    service = ReportAssemblerService(source)
    scope = AssembleScope(workspace_id="ws-1", **scope_kwargs)
    return service.assemble(scope), source


class TestHistogram:
    def test_counts_per_band(self):
        # Distinct signals so the two highs are genuinely different issues and
        # do not collapse under dedup (which keys on severity+service+signal).
        findings = [
            _finding(fid_hint="1", severity="high", title="High A", signal="auth 5xx spike"),
            _finding(fid_hint="2", severity="high", title="High B", signal="db connection refused"),
            _finding(fid_hint="3", severity="medium", title="Medium A", signal="slow query"),
            _finding(fid_hint="4", severity="low", title="Low A", signal="deprecation warning"),
            _finding(fid_hint="5", severity="critical", title="Crit A", signal="rce attempt"),
        ]
        report, _ = _assemble(findings)
        assert report.histogram.counts == {
            "critical": 1,
            "high": 2,
            "medium": 1,
            "low": 1,
            "informational": 0,
        }
        assert report.histogram.total == 5
        assert report.histogram.highest_band == "critical"

    def test_identical_findings_collapse_with_occurrence_count(self):
        # 320 findings that differ only by task id (same severity/service/signal)
        # collapse to one distinct issue observed 320 times.
        findings = [_finding(fid_hint=str(i), severity="high", title=f"celery task {i}") for i in range(320)]
        report, _ = _assemble(findings)
        assert report.histogram.total == 1
        assert report.matrix[0].occurrences == 320
        assert report.raw_finding_count == 320

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
        assert any("Distinct findings: 0" in t for t in report.grounding_texts)


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
        assert source.last_query.sources == ("ai.log_watch.error",)

    def test_unknown_kind_raises(self):
        source = FakeFindingSource([])
        service = ReportAssemblerService(source)
        with pytest.raises(UnknownReportKind):
            service.assemble(AssembleScope(workspace_id="ws-1", kind="nope"))


class TestAccountingIsCarriedNotDiscarded:
    """Whatever the port could not return, the assembled report STATES."""

    def test_truncation_reaches_the_report_and_the_grounding(self):
        findings = [_finding(fid_hint=str(i), severity="high", title=f"Issue {i}") for i in range(3)]
        source = FakeFindingSource(findings, extra_matched=97)
        report = ReportAssemblerService(source).assemble(AssembleScope(workspace_id="ws-1"))

        assert report.total_matched == 100
        assert report.truncated_count == 97
        assert report.is_truncated
        corpus = " ".join(report.grounding_texts)
        assert "100 findings matched this report's scope" in corpus
        assert "97 findings were not included" in corpus

    def test_untriaged_findings_are_counted_and_grounded(self):
        findings = [
            _finding(fid_hint="1", severity="high", title="Triaged one", signal="a"),
            _finding(fid_hint="2", severity="high", title="Nobody looked", signal="b", on_board=False),
        ]
        report, _ = _assemble(findings)

        assert report.untriaged_count == 1
        by_title = {t.title: t for t in report.technical_findings}
        assert by_title["Nobody looked"].triage.label == "Untriaged"
        assert by_title["Triaged one"].triage.label == "Todo — alice"
        assert any("have not been triaged" in t for t in report.grounding_texts)

    def test_sample_data_is_counted_marked_and_grounded(self):
        findings = [
            _finding(fid_hint="1", severity="high", title="Demo", signal="a", is_sample=True),
            _finding(fid_hint="2", severity="high", title="Real", signal="b"),
        ]
        report, _ = _assemble(findings)

        assert report.sample_finding_count == 1
        assert report.contains_sample_data
        assert {t.title: t.is_sample for t in report.technical_findings} == {"Demo": True, "Real": False}
        assert any("CONTAINS SAMPLE DATA" in t for t in report.grounding_texts)

    def test_the_kinds_inclusion_policy_reaches_the_port(self):
        report, source = _assemble([])
        # Pentest excludes terminal findings, includes sample data — and the
        # scope goes out in SSOT vocabulary (every source), not board prefixes.
        assert source.last_query.include_resolved is False
        assert source.last_query.include_suppressed is False
        assert source.last_query.include_sample is True
        assert source.last_query.source_prefixes == ()
        assert report.excluded_resolved == 0


class TestIdentityDedupDoesNotUndercount:
    def test_distinct_ssot_findings_are_never_fuzzily_merged(self):
        """Two open security groups differ only by a hex id — the fuzzy board
        signature would collapse them into one and undercount the report."""
        findings = [
            _finding(
                fid_hint="1",
                severity="critical",
                title="Security group sg-0a1b2c3d4e5f allows SSH from 0.0.0.0/0",
                signal="Security group sg-0a1b2c3d4e5f allows SSH from 0.0.0.0/0",
                dedup_key="cloud_posture.prowler|sg-0a1b2c3d4e5f",
            ),
            _finding(
                fid_hint="2",
                severity="critical",
                title="Security group sg-9f8e7d6c5b4a allows SSH from 0.0.0.0/0",
                signal="Security group sg-9f8e7d6c5b4a allows SSH from 0.0.0.0/0",
                dedup_key="cloud_posture.prowler|sg-9f8e7d6c5b4a",
            ),
        ]
        report, _ = _assemble(findings)
        assert report.distinct_finding_count == 2
        assert all(row.occurrences == 1 for row in report.matrix)

    def test_board_findings_still_collapse_fuzzily(self):
        """The board is per-occurrence and has no stable identity, so the fuzzy
        signature must keep working for it — unchanged behaviour."""
        findings = [_finding(fid_hint=str(i), severity="high", title=f"celery task {i}") for i in range(50)]
        report, _ = _assemble(findings)
        assert report.distinct_finding_count == 1
        assert report.matrix[0].occurrences == 50


class TestInformationalBand:
    def test_an_informational_finding_is_not_inflated_to_low(self):
        findings = [_finding(fid_hint="1", severity="informational", title="FYI")]
        report, _ = _assemble(findings)
        assert report.histogram.counts["informational"] == 1
        assert report.histogram.counts["low"] == 0
        assert report.technical_findings[0].severity.band == "informational"
        assert report.technical_findings[0].cvss == 0.0

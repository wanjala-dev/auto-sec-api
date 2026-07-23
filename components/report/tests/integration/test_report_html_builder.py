"""Integration test: the pentest template renders from assembled data.

Proves the whole render path (context mapper → Django template) produces HTML
carrying the Faura structure — cover with the workspace org name, the severity
histogram, the findings matrix, a per-finding severity banner + evidence
terminal, and both appendices. Rendering-only; no PDF, no Gotenberg.
"""

from __future__ import annotations

import pytest

from components.report.domain.entities.assembled_report_entity import (
    AssembledReport,
    EvidenceBlock,
    MatrixRow,
    ReportNarrative,
    SeverityHistogram,
    TechnicalFinding,
)
from components.report.domain.value_objects.severity import Severity
from components.report.infrastructure.adapters.report_html_builder import build_report_html

pytestmark = pytest.mark.integration


def _assembled() -> AssembledReport:
    tech = TechnicalFinding(
        fid="F-01",
        title="Repeated auth failures on auth-svc",
        category="Log Anomaly",
        severity=Severity("high"),
        affected_asset="auth-svc (ERROR, 42 records)",
        description="Brute-force pattern detected.\n\nProbable cause: exposed login endpoint.",
        remediation=("Rate-limit the login endpoint.", "Rotate affected credentials."),
        evidence=EvidenceBlock(
            lines=("SERVICE  auth-svc", "LEVEL    ERROR", "LOG_LINE  401 x 42"),
            caption="detector confidence: high",
        ),
    )
    hist = SeverityHistogram(counts={"critical": 0, "high": 1, "medium": 0, "low": 0})
    return AssembledReport(
        kind="pentest",
        histogram=hist,
        matrix=(MatrixRow(fid="F-01", category="Log Anomaly", title=tech.title, severity=tech.severity),),
        technical_findings=(tech,),
        narrative=ReportNarrative(
            executive_summary="One finding was identified: 1 High.",
            overall_assessment="The finding clusters on auth-svc.",
            faithful=True,
        ),
        grounding_texts=("Total findings: 1.",),
    )


class TestPentestTemplateRender:
    def test_renders_full_structure(self):
        html = build_report_html(
            assembled=_assembled(),
            kind="pentest",
            title="Acme Penetration Test Report",
            scope={
                "client_name": "Acme SOC",
                "scope_summary": "Web + cloud",
                "target": "auth-svc",
                "approach": "Grey-box",
            },
            workspace_id="00000000-0000-0000-0000-000000000000",
            workspace_name="Acme SOC",
            workspace_logo_url="",
        )
        # Cover carries the org identity + report title.
        assert "Acme SOC" in html
        assert "Penetration Test Report" in html
        # Histogram + matrix.
        assert "Vulnerabilities by Severity" in html
        assert "Findings Matrix" in html
        assert "F-01" in html
        # Technical finding: banner + evidence terminal.
        assert "Repeated auth failures on auth-svc" in html
        assert "Recommended Remediation" in html
        assert "Rate-limit the login endpoint." in html
        assert "auth-svc" in html
        assert "evidence" in html
        # Appendices.
        assert "Appendix A" in html
        assert "Appendix B" in html
        # Indicative-CVSS caveat surfaces.
        assert "indicative" in html.lower()

    def test_empty_board_renders_honest_report(self):
        empty = AssembledReport(
            kind="pentest",
            histogram=SeverityHistogram(counts={"critical": 0, "high": 0, "medium": 0, "low": 0}),
            matrix=(),
            technical_findings=(),
            narrative=ReportNarrative(executive_summary="No findings were surfaced.", overall_assessment=""),
            grounding_texts=("Total findings: 0.",),
        )
        html = build_report_html(
            assembled=empty,
            kind="pentest",
            title="Empty Report",
            scope={},
            workspace_id="00000000-0000-0000-0000-000000000000",
            workspace_name="Quiet Org",
            workspace_logo_url="",
        )
        assert "No technical findings" in html
        assert "No findings to list" in html

    def test_unfaithful_narrative_surfaces_reviewer_note(self):
        assembled = _assembled()
        unfaithful = AssembledReport(
            kind=assembled.kind,
            histogram=assembled.histogram,
            matrix=assembled.matrix,
            technical_findings=assembled.technical_findings,
            narrative=ReportNarrative(
                executive_summary="We found 99 issues.",
                overall_assessment="",
                faithful=False,
                unsupported_numbers=("99",),
            ),
            grounding_texts=assembled.grounding_texts,
        )
        html = build_report_html(
            assembled=unfaithful,
            kind="pentest",
            title="R",
            scope={},
            workspace_id="00000000-0000-0000-0000-000000000000",
            workspace_name="Org",
            workspace_logo_url="",
        )
        assert "could not be grounded" in html
        assert "99" in html

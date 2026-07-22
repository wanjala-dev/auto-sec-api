"""Unit tests for the faithfulness-gated narrative writer.

Uses a fake LLM (records prompts, returns canned prose) and the REAL
deterministic faithfulness verifier — the grounding check is pure, so testing
against the real thing is honest. Locks the load-bearing property: a figure the
prose invents that is not in the grounding corpus flips ``faithful`` to False.
"""

from __future__ import annotations

import pytest

from components.agents.domain.services.faithfulness_verifier import FaithfulnessVerifier
from components.report.domain.entities.assembled_report import (
    AssembledReport,
    EvidenceBlock,
    MatrixRow,
    SeverityHistogram,
    TechnicalFinding,
)
from components.report.domain.value_objects.severity import Severity
from components.report.infrastructure.adapters.grounded_report_narrative_adapter import (
    GroundedReportNarrativeAdapter,
)

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeLlm:
    """Returns queued responses in order; records prompts."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def invoke(self, prompt: str, **kwargs):
        self.prompts.append(prompt)
        return _Resp(self._responses.pop(0) if self._responses else "")


def _assembled(count: int = 2) -> AssembledReport:
    techs = tuple(
        TechnicalFinding(
            fid=f"F-0{i}",
            title=f"Finding {i}",
            category="Log Anomaly",
            severity=Severity("high" if i == 1 else "low"),
            affected_asset="auth-svc",
            description="A grounded description.",
            remediation=("Rotate credentials.",),
            evidence=EvidenceBlock(lines=("SERVICE auth-svc",), caption="confidence: high"),
        )
        for i in range(1, count + 1)
    )
    hist = SeverityHistogram(counts={"critical": 0, "high": 1, "medium": 0, "low": 1})
    matrix = tuple(MatrixRow(fid=t.fid, category=t.category, title=t.title, severity=t.severity) for t in techs)
    grounding = (
        "Total findings: 2.",
        "Critical severity findings: 0.",
        "High severity findings: 1.",
        "Medium severity findings: 0.",
        "Low severity findings: 1.",
        "F-01 Finding 1. Category Log Anomaly. Severity High, indicative CVSS 8.0. Affected asset auth-svc.",
        "F-02 Finding 2. Category Log Anomaly. Severity Low, indicative CVSS 2.5. Affected asset auth-svc.",
    )
    return AssembledReport(
        kind="pentest",
        histogram=hist,
        matrix=matrix,
        technical_findings=techs,
        grounding_texts=grounding,
    )


def _adapter(responses: list[str]) -> tuple[GroundedReportNarrativeAdapter, FakeLlm]:
    llm = FakeLlm(responses)
    adapter = GroundedReportNarrativeAdapter(llm_port=llm, verifier=FaithfulnessVerifier())
    return adapter, llm


class TestGroundedNarrative:
    def test_grounded_prose_is_faithful(self):
        # Prose only cites the real counts (2 findings, 1 high, 1 low).
        adapter, _ = _adapter(
            [
                "The engagement reviewed the systems in scope. 2 findings were identified: 1 High and 1 Low.",
                "The findings cluster around log anomalies on auth-svc.",
            ]
        )
        result = adapter.write(
            assembled=_assembled(),
            workspace_name="Acme SOC",
            engagement_title="Assessment",
            scope_summary="the monitored services",
        )
        assert result.faithful is True
        assert result.unsupported_numbers == ()
        assert "2 findings" in result.executive_summary

    def test_invented_figure_flags_unfaithful(self):
        # The LLM invents "47 findings" and "$50,000" — neither in the corpus.
        # Both re-write attempts also invent, so it lands flagged.
        adapter, _ = _adapter(
            [
                "We found 47 findings costing $50,000 to remediate.",
                "The 47 issues span many systems.",
                "We found 47 findings costing $50,000 to remediate.",
                "The 47 issues span many systems.",
            ]
        )
        result = adapter.write(
            assembled=_assembled(),
            workspace_name="Acme SOC",
            engagement_title="Assessment",
            scope_summary="scope",
        )
        assert result.faithful is False
        assert any("47" in n for n in result.unsupported_numbers)

    def test_findings_not_in_input_are_never_fed_to_the_llm(self):
        # The prompt the LLM receives must only contain the supplied findings.
        adapter, llm = _adapter(["Grounded exec.", "Grounded assessment."])
        adapter.write(
            assembled=_assembled(),
            workspace_name="Acme SOC",
            engagement_title="Assessment",
            scope_summary="scope",
        )
        joined = " ".join(llm.prompts)
        assert "Finding 1" in joined and "Finding 2" in joined
        # A finding id that was never assembled must not appear.
        assert "F-99" not in joined
        assert "Finding 3" not in joined

    def test_rewrite_recovers_when_second_attempt_is_grounded(self):
        adapter, llm = _adapter(
            [
                "We found 99 findings.",  # unfaithful
                "Themes across the 99.",  # unfaithful
                "2 findings were identified: 1 High and 1 Low.",  # grounded rewrite
                "Themes cluster on auth-svc log anomalies.",  # grounded rewrite
            ]
        )
        result = adapter.write(
            assembled=_assembled(),
            workspace_name="Acme SOC",
            engagement_title="Assessment",
            scope_summary="scope",
        )
        assert result.faithful is True
        assert len(llm.prompts) == 4  # 2 initial + 2 rewrite

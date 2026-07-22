"""Faithfulness-gated narrative writer.

Implements :class:`ReportNarrativePort`. Writes the executive summary and the
overall-assessment prose over the assembled findings, then runs the deterministic
faithfulness verifier (the same one the content newsletter gate uses) over the
prose against the assembler's grounding corpus. If a figure the prose states is
not grounded, the writer regenerates ONCE with the unsupported figures fed back;
if it still cannot ground them, the narrative is returned flagged (``faithful =
False``) with the unsupported items so the operator sees it before approving —
we never silently ship an ungrounded claim.

The LLM is reached through the knowledge ``LlmPort`` (via the agents provider);
no ``import openai`` here. The verifier is reached through the agents
application provider (never the agents domain directly).
"""

from __future__ import annotations

import logging

from components.report.application.ports.report_narrative_port import ReportNarrativePort
from components.report.domain.entities.assembled_report import AssembledReport, ReportNarrative

logger = logging.getLogger(__name__)


_SYSTEM_RULES = (
    "You are a senior penetration-test analyst writing the prose sections of a "
    "client deliverable. You write ONLY from the findings supplied below. You "
    "MUST NOT introduce any finding, system, asset, number, or CVSS score that "
    "is not present in the supplied findings. Every count you state must match "
    "the supplied totals exactly. Do not invent a composite risk score. Write "
    "in plain, professional prose — no hype, no marketing adjectives."
)


class GroundedReportNarrativeAdapter(ReportNarrativePort):
    def __init__(self, *, llm_port=None, verifier=None) -> None:
        # Injected for tests; resolved lazily in prod so import stays cheap.
        self._llm = llm_port
        self._verifier = verifier

    # ── port ────────────────────────────────────────────────────────────

    def write(
        self,
        *,
        assembled: AssembledReport,
        workspace_name: str,
        engagement_title: str,
        scope_summary: str,
    ) -> ReportNarrative:
        llm = self._resolve_llm()
        verifier = self._resolve_verifier()
        grounding = list(assembled.grounding_texts)

        exec_prompt = self._exec_summary_prompt(assembled, workspace_name, engagement_title, scope_summary)
        assess_prompt = self._overall_assessment_prompt(assembled, workspace_name)

        exec_summary = self._invoke(llm, exec_prompt)
        overall = self._invoke(llm, assess_prompt)

        combined = f"{exec_summary}\n\n{overall}"
        report = verifier.verify(generated_html=combined, grounding_texts=grounding)

        if not report.ok:
            # One grounded re-write with the unsupported figures fed back.
            feedback = (
                "The previous draft cited figures not present in the findings: "
                f"{', '.join(report.unsupported_numbers)}. Rewrite using ONLY the "
                "counts and CVSS scores present in the supplied findings."
            )
            exec_summary = self._invoke(llm, f"{exec_prompt}\n\n{feedback}")
            overall = self._invoke(llm, f"{assess_prompt}\n\n{feedback}")
            combined = f"{exec_summary}\n\n{overall}"
            report = verifier.verify(generated_html=combined, grounding_texts=grounding)

        if not report.ok:
            logger.warning(
                "report.narrative_ungrounded workspace=%s unsupported=%s",
                workspace_name,
                report.unsupported_numbers,
            )

        return ReportNarrative(
            executive_summary=exec_summary.strip(),
            overall_assessment=overall.strip(),
            faithful=report.ok,
            unsupported_numbers=tuple(report.unsupported_numbers),
            unsupported_names=tuple(report.unsupported_names),
        )

    # ── prompts ─────────────────────────────────────────────────────────

    def _findings_block(self, assembled: AssembledReport) -> str:
        lines = [f"Total findings: {assembled.histogram.total}."]
        for band, count in assembled.histogram.ordered():
            lines.append(f"  {band.capitalize()}: {count}")
        lines.append("")
        for tech in assembled.technical_findings:
            lines.append(
                f"{tech.fid} [{tech.severity.label}, indicative CVSS {tech.cvss}] "
                f"{tech.title} — {tech.category}, affected: {tech.affected_asset}."
            )
        return "\n".join(lines)

    def _exec_summary_prompt(
        self, assembled: AssembledReport, workspace_name: str, engagement_title: str, scope_summary: str
    ) -> str:
        return (
            f"{_SYSTEM_RULES}\n\n"
            f"Engagement: {engagement_title or 'Security assessment'} for {workspace_name}.\n"
            f"Scope: {scope_summary or 'the systems in scope'}.\n\n"
            f"Findings:\n{self._findings_block(assembled)}\n\n"
            "Write the Executive Summary: 2-4 short paragraphs. Describe the engagement "
            "and what was assessed, then give a Findings Overview stating exactly how many "
            "issues were found and their split across the severity bands (use the counts "
            "above verbatim). State the highest severity band reached. If there were no "
            "findings, say so plainly. Prose only, no headings, no bullet lists."
        )

    def _overall_assessment_prompt(self, assembled: AssembledReport, workspace_name: str) -> str:
        return (
            f"{_SYSTEM_RULES}\n\n"
            f"Findings:\n{self._findings_block(assembled)}\n\n"
            "Write the Overall Assessment: 1-3 short paragraphs of thematic prose that "
            "groups the findings into the recurring themes you see across them (e.g. access "
            "control, transport/infrastructure hardening, configuration). Reference the "
            "themes present in the findings above only — do not introduce systems or "
            "figures not listed. If there were no findings, state that the assessment "
            "surfaced no issues in the scope reviewed. Prose only."
        )

    # ── plumbing ────────────────────────────────────────────────────────

    def _invoke(self, llm, prompt: str) -> str:
        try:
            response = llm.invoke(prompt)
            return getattr(response, "content", "") or ""
        except Exception:
            logger.exception("report.narrative_llm_failed")
            # Honest fallback — never fabricate; the section says the prose
            # could not be generated so the operator writes it manually.
            return "This section could not be generated automatically. Please review the findings and author it."

    def _resolve_llm(self):
        if self._llm is not None:
            return self._llm
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider

        return AILlmProvider().get_default_port(model_name="gpt-3.5-turbo", temperature=0.3)

    def _resolve_verifier(self):
        if self._verifier is not None:
            return self._verifier
        from components.agents.application.providers.ai_provider import AIProvider

        return AIProvider.build_faithfulness_verifier()

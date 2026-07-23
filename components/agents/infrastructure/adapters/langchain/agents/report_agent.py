"""Report Agent — the assessor's scribe for client-deliverable reports.

Turns findings already on the SOC board into a workspace-branded PDF deliverable
(pentest first). It NEVER assesses — it does not decide severity, invent a
finding, or write to the board. It assembles the findings that already exist,
narrates the summary prose over them (grounded + faithfulness-gated in the report
context), renders the branded PDF, and hands back a report the operator reviews
and approves.

Two tools:
  - ``generate_pentest_report`` — create the report + enqueue generation
    (reversible write; the report starts as a draft an owner/admin approves
    before it can be downloaded).
  - ``narrate_report_sections`` — write the grounded exec-summary + overall-
    assessment prose over supplied structured findings, WITHOUT persisting
    anything. The faithfulness gate in the report context guarantees the prose
    introduces no finding not in the input.

Cross-context application imports (the report context's providers + use cases)
are allowed by the architecture manifesto; infrastructure imports are not — so
this agent reaches the report pipeline through ``ReportProvider`` only.

Auto-discovered (ADR 0003) — no edits to base.py or the registry.
"""

import json
import logging

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)

logger = logging.getLogger(__name__)


def _parse_json(input_str: str) -> dict:
    raw = (input_str or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw) if raw.startswith("{") else {"value": raw}
        return data if isinstance(data, dict) else {"value": data}
    except (ValueError, TypeError):
        return {"value": raw}


@register_agent(
    "report_agent",
    aliases=("report", "reporting", "pentest_report", "security_report"),
)
class ReportAgent(WorkspaceContextMixin, BaseAgent):
    """Generates client-deliverable branded reports from board findings."""

    profile = {
        "name": "Report Agent",
        "summary": (
            "Turns the findings already on the SOC board into a client-ready, "
            "workspace-branded PDF deliverable — a penetration-test report today "
            "(the report kind is extensible). It assembles the scoped findings "
            "deterministically (severity histogram, findings matrix, per-finding "
            "technical sections with the detector's own evidence), writes the "
            "executive-summary and overall-assessment prose grounded strictly in "
            "those findings (faithfulness-gated — it can never cite a finding not "
            "on the board), and renders the branded PDF for an owner/admin to "
            "approve. It is the assessor's scribe: it never assigns severity, "
            "files a finding, or writes to the board."
        ),
        "capabilities": [
            "Generate a workspace-branded pentest report PDF from the board's findings",
            "Scope a report to specific finding source types or a date window",
            "Write grounded executive-summary + overall-assessment prose over supplied findings",
            "Report generation status and where the deliverable stands in the approve/download flow",
        ],
        "sample_prompts": [
            "Generate a pentest report",
            "Write the security report for this quarter's findings",
            "Produce a client-ready penetration test report PDF",
        ],
    }

    @tool(
        name="generate_pentest_report",
        description=(
            "Generate a client-deliverable, workspace-branded penetration-test "
            "report PDF from the findings on the SOC board. Input: optional JSON "
            '{"title": "...", "scope": {"scope_summary": "...", "target": "...", '
            '"approach": "...", "source_types": ["ai.log_watch.error", ...], '
            '"since": "ISO-date", "until": "ISO-date"}}. All fields optional — with '
            "no input it reports over every AI finding on the board. Creates the "
            "report in DRAFT and enqueues generation; the deliverable must be "
            "approved by an owner/admin before it can be downloaded. Returns the "
            "report id and status. Does NOT assess or modify any finding."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def generate_pentest_report(self, input_str: str = "") -> str:
        from components.report.application.providers.report_provider import ReportProvider
        from components.report.workers.tasks import generate_report

        data = _parse_json(input_str)
        scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
        title = str(data.get("title") or "").strip() or "Penetration Test Report"

        try:
            report = ReportProvider.repository().create(
                workspace_id=str(self.workspace_id),
                kind="pentest",
                title=title,
                scope=scope or {},
                created_by_id=str(self.user_id) if getattr(self, "user_id", None) else None,
            )
        except Exception:
            logger.exception("report_agent.generate_failed workspace_id=%s", self.workspace_id)
            return "Could not start the report — the report could not be created."

        try:
            generate_report.delay(report_id=report["id"], workspace_id=str(self.workspace_id))
        except Exception:
            logger.exception("report_agent.enqueue_failed report_id=%s", report["id"])
            return (
                f"Report {report['id']} was created as a draft but could not be enqueued for "
                "generation — retry shortly."
            )

        logger.info(
            "report_agent.generate report_id=%s workspace_id=%s",
            report["id"],
            self.workspace_id,
        )
        return json.dumps(
            {
                "report_id": report["id"],
                "status": "draft",
                "message": (
                    "The penetration test report is generating. Once it finishes it will be "
                    "in the Reports surface for an owner or admin to approve, after which it "
                    "can be downloaded. Assess nothing yourself — this only compiles findings "
                    "already on the board."
                ),
            }
        )

    @tool(
        name="narrate_report_sections",
        description=(
            "Write the grounded executive-summary and overall-assessment prose "
            "over a supplied set of structured findings, WITHOUT persisting or "
            "generating anything. Input: JSON with a `findings` list, each "
            '{"title", "severity", "category", "affected_asset"}, and optional '
            "`engagement_title` / `scope_summary`. Returns the two prose sections. "
            "The prose is faithfulness-checked — it can never introduce a finding, "
            "count, or CVSS not present in the supplied findings. Use this to draft "
            "narrative for review; use generate_pentest_report to produce the PDF."
        ),
        risk=ToolRisk.READ,
    )
    def narrate_report_sections(self, input_str: str = "") -> str:
        # Cross-context APPLICATION import only (allowed) — the use case owns
        # the report domain entities + assembler; this adapter never touches
        # another context's domain layer.
        from components.report.application.providers.report_provider import ReportProvider

        data = _parse_json(input_str)
        raw_findings = data.get("findings")
        if not isinstance(raw_findings, list) or not raw_findings:
            return "Provide a `findings` list to narrate over — the scribe never invents findings."

        use_case = ReportProvider.build_narrate_supplied_findings_use_case()
        result = use_case.execute(
            findings=raw_findings,
            workspace_name=self._workspace_name(),
            engagement_title=str(data.get("engagement_title") or ""),
            scope_summary=str(data.get("scope_summary") or ""),
        )
        if result.get("error") == "no_valid_findings":
            return "No valid findings were supplied to narrate over."
        return json.dumps(result)

    # ── system prompt: scribe-not-assessor discipline ────────────────────

    def _build_system_message(self) -> str:
        base = super()._build_system_message()
        return base + (
            "\n\nReporting rules (non-negotiable):\n"
            "- You are the assessor's SCRIBE, never the assessor. You compile "
            "findings that already exist on the board into a deliverable — you "
            "do not decide severity, invent a finding, or write to the board.\n"
            "- Every figure in a report comes from the findings on the board. "
            "The narrative is faithfulness-gated: it can never cite a finding, "
            "count, or CVSS not present in the supplied findings.\n"
            "- CVSS scores are indicative (mapped from the severity band; this "
            "product computes no CVSS vectors) — say so if asked.\n"
            "- A generated report is a DRAFT until an owner or admin approves "
            "it; only then can it be downloaded. Tell the user that flow.\n"
            "- To produce the PDF use generate_pentest_report. To draft prose "
            "for review without generating, use narrate_report_sections."
        )

    def _workspace_name(self) -> str:
        try:
            from components.report.application.providers.report_provider import ReportProvider

            return ReportProvider.workspace_identity().get(workspace_id=str(self.workspace_id)).name
        except Exception:
            logger.exception("report_agent.workspace_name_failed workspace_id=%s", self.workspace_id)
            return ""

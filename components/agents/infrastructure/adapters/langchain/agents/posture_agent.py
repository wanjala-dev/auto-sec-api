"""Security Posture Agent — SOC-ops posture with a CTEM frame.

The Phase-1 posture specialist from
``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md`` §3.1: a READ-ONLY
aggregator over the outputs the rest of the fleet already produces — board
findings, triage stamps, deep-run telemetry, spend records and human votes.
Every tool wraps a deterministic function in
``components/agents/application/services/posture_service.py`` 1:1; the LLM
narrates ONLY what the tools return (no LLM over raw data, no invented
numbers, and constitutionally NO composite "posture score" — the industry's
most-gamed metric, vision §2.1).

Persona lensing (vision §1): the ``get_posture_report`` tool takes a persona
(``engineer`` | ``executive``) and returns the SAME facts in a different
structure — engineer gets the full drill-down with finding ids, executive
gets the NACD board shape (threat environment / financial / maturity /
forward-looking). The framing lives in the tool's response structure, not in
LLM imagination.

Auto-discovered (ADR 0003) — no edits to base.py or the registry.
"""

import json
import logging

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.services import posture_service
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 7


def _parse_input(input_str: str) -> dict:
    raw = (input_str or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"value": data}
    except (ValueError, TypeError):
        return {"value": raw}


def _parse_window_days(input_str: str) -> int:
    data = _parse_input(input_str)
    try:
        days = int(data.get("window_days") or data.get("value") or _DEFAULT_WINDOW_DAYS)
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_DAYS
    return days if 1 <= days <= 90 else _DEFAULT_WINDOW_DAYS


@register_agent(
    "posture_agent",
    aliases=("posture", "security_posture", "posture_review", "soc_posture"),
)
class PostureAgent(WorkspaceContextMixin, BaseAgent):
    """Reports the workspace's operational security posture, with evidence."""

    profile = {
        "name": "Security Posture Agent",
        "summary": (
            "Reports how the detect-and-respond machine is performing — open "
            "findings and backlog, median response-time KPIs against industry "
            "bands, agent-fleet health (run success, rubric pass rate, cost, "
            "human votes), and week-over-week trend deltas — every number "
            "computed deterministically from board and telemetry data, with "
            "its evidence attached. Frames the story on the CTEM stages "
            "(Discovery, Prioritization, Validation, Mobilization) and can "
            "render the same facts through an engineer or executive lens."
        ),
        "capabilities": [
            "Summarize open findings by severity and kind, plus the needs-human backlog",
            "Report median triage/acknowledgment latency per severity against industry benchmark bands",
            "Report agent-fleet health: run success rate, rubric verdicts, cost, human vote ratio",
            "Report week-over-week trend deltas (findings created, escalations, backlog)",
            "Compose a full posture report through an engineer or executive (NACD) lens",
        ],
        "sample_prompts": [
            "What is our security posture?",
            "Give me an executive security summary",
            "Are we triaging critical findings inside the industry band?",
            "How healthy is the agent fleet this week?",
        ],
    }

    # ── Tools — 1:1 wrappers over posture_service (deterministic, READ) ──

    @tool(
        name="get_findings_posture",
        description=(
            "Current findings posture: open findings by severity and kind, "
            "needs-human backlog, oldest-untriaged age, triage counts (24h + "
            "window) and the toil split (auto-triaged vs escalated). Input: "
            'optional JSON {"window_days": 7}. Returns JSON with sample task '
            "ids as evidence."
        ),
        risk=ToolRisk.READ,
    )
    def get_findings_posture(self, input_str: str = "") -> str:
        window_days = _parse_window_days(input_str)
        try:
            data = posture_service.findings_posture(self.workspace_id, window_days=window_days)
        except Exception:
            logger.exception("get_findings_posture failed workspace_id=%s", self.workspace_id)
            return "Could not compute findings posture — the board data could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_response_kpis",
        description=(
            "Response-time KPIs: MEDIAN finding-created→triage latency per "
            "severity reported against industry benchmark bands (critical 1h, "
            "high 2h, medium 4h, low 8h), plus acknowledgment latency. Each "
            "KPI is {median_hours, band_hours, within_band, sample_count}. "
            'Input: optional JSON {"window_days": 7}. Returns JSON.'
        ),
        risk=ToolRisk.READ,
    )
    def get_response_kpis(self, input_str: str = "") -> str:
        window_days = _parse_window_days(input_str)
        try:
            data = posture_service.response_kpis(self.workspace_id, window_days=window_days)
        except Exception:
            logger.exception("get_response_kpis failed workspace_id=%s", self.workspace_id)
            return "Could not compute response KPIs — the board data could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_fleet_health",
        description=(
            "Agent-fleet health: deep-run success rate, rubric verdict "
            "distribution and pass rate, total + per-day cost in USD, human "
            "thumbs-up/down ratio, and dispatch counts per specialist. Input: "
            'optional JSON {"window_days": 7}. Returns JSON.'
        ),
        risk=ToolRisk.READ,
    )
    def get_fleet_health(self, input_str: str = "") -> str:
        window_days = _parse_window_days(input_str)
        try:
            data = posture_service.fleet_health(self.workspace_id, window_days=window_days)
        except Exception:
            logger.exception("get_fleet_health failed workspace_id=%s", self.workspace_id)
            return "Could not compute fleet health — run/telemetry data could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_forward_outlook",
        description=(
            "Forward outlook: this-week vs last-week deltas for findings "
            "created and needs-human escalations, plus the current needs-human "
            "backlog. Honest arithmetic deltas only — no forecasting model. "
            "No input. Returns JSON."
        ),
        risk=ToolRisk.READ,
    )
    def get_forward_outlook(self, input_str: str = "") -> str:
        try:
            data = posture_service.forward_outlook(self.workspace_id)
        except Exception:
            logger.exception("get_forward_outlook failed workspace_id=%s", self.workspace_id)
            return "Could not compute the forward outlook — the board data could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_posture_report",
        description=(
            "Full posture report composing findings posture, response KPIs, "
            "fleet health and forward outlook, framed for a persona. Input: "
            'JSON {"persona": "engineer"|"executive", "window_days": 7} (or '
            "the bare persona string; defaults to engineer). engineer = full "
            "drill-down with finding ids; executive = NACD board shape "
            "(threat environment / financial / maturity / forward-looking). "
            "Same facts either way. Returns JSON with a ctem_mapping section."
        ),
        risk=ToolRisk.READ,
    )
    def get_posture_report(self, input_str: str = "") -> str:
        data = _parse_input(input_str)
        persona = str(data.get("persona") or data.get("value") or posture_service.PERSONA_ENGINEER).strip().lower()
        if persona not in posture_service.PERSONAS:
            return f"Unknown persona {persona!r} — use one of: {', '.join(posture_service.PERSONAS)}."
        window_days = _parse_window_days(input_str)
        try:
            report = posture_service.posture_report(self.workspace_id, persona=persona, window_days=window_days)
        except Exception:
            logger.exception(
                "get_posture_report failed workspace_id=%s persona=%s",
                self.workspace_id,
                persona,
            )
            return "Could not compose the posture report — underlying posture data could not be read."
        return json.dumps(report, default=str)

    # ── System prompt: CTEM narrative + honesty rules ────────────────────

    def _build_system_message(self) -> str:
        base = super()._build_system_message()
        return base + (
            "\n\nPosture reporting rules (non-negotiable):\n"
            "- Answer ONLY from tool output. Every number you state must "
            "appear in a tool result from this conversation — never estimate, "
            "extrapolate, or fill gaps from memory.\n"
            "- NEVER invent a composite 'posture score'. Report components "
            "(findings, KPIs, fleet health, outlook) side by side; a single "
            "blended number is the industry's most-gamed metric and this "
            "product deliberately does not have one.\n"
            "- Always state the time window a number covers (the tools return "
            "window_days — repeat it).\n"
            "- Latency KPIs are MEDIANS against industry bands; say 'median' "
            "and name the band when reporting them.\n"
            "- When a section carries no_data=true or a null value, say "
            "plainly that there is no data yet for that dimension — never "
            "substitute a guess.\n"
            "- Frame the summary on the CTEM stages the tools map for you: "
            "Discovery (detectors filing findings), Prioritization (severity/"
            "impact), Validation (grounded verification + rubric grading), "
            "Mobilization (triage actions, board moves, draft PRs). Use the "
            "ctem_mapping section from get_posture_report when present.\n"
            "- Posture facts should link to action: point the operator at the "
            "sample task ids / backlog the numbers came from."
        )

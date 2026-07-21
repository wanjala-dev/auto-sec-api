"""AI Governance Agent — AI-SPM over our own fleet (vision §3.4).

The Phase-2 governance specialist from
``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md``: dogfoods our own AI
governance — which agent used which tool at which risk tier, who granted
which capability (and whether the grant left an audit trail), the HITL
approval ledger (draft PRs a human explicitly approved), the credential
surface the AI can reach (GitHubConnection scopes — NEVER token material),
and the kill-switch state.

Every tool wraps a deterministic function in
``components/agents/application/services/ai_governance_service.py`` 1:1;
the LLM narrates ONLY what the tools return — no invented numbers, and
where the platform does not record something (denied approvals, pre-slice
grant history) the tools say so and the agent repeats it honestly.

READ-ONLY by design: this agent is an assessor, not an actor. The kill
switch itself is deliberately NOT a tool here — flipping it is a human-only
action behind the owner/admin-gated ``POST /ai/agents/kill-switch/``
endpoint. An AI that can disable (or re-enable) its own containment control
defeats the point of the control.

Auto-discovered (ADR 0003) — no edits to base.py or the registry.
"""

import json
import logging

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.services import ai_governance_service
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
_HITL_DEFAULT_WINDOW_DAYS = 30


def _parse_input(input_str: str) -> dict:
    raw = (input_str or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"value": data}
    except (ValueError, TypeError):
        return {"value": raw}


def _parse_window_days(input_str: str, default: int = _DEFAULT_WINDOW_DAYS) -> int:
    data = _parse_input(input_str)
    try:
        days = int(data.get("window_days") or data.get("value") or default)
    except (TypeError, ValueError):
        return default
    return days if 1 <= days <= 90 else default


@register_agent(
    "ai_governance_agent",
    aliases=("ai_governance", "governance", "ai_audit", "ai_activity"),
)
class AiGovernanceAgent(WorkspaceContextMixin, BaseAgent):
    """Reports what the AI fleet did, may do, and how to stop it — with evidence."""

    profile = {
        "name": "AI Governance Agent",
        "summary": (
            "Audits the workspace's own AI: which agents ran and which tools "
            "they invoked at which risk tier (chat vs detector dispatch), "
            "which risk-gating capabilities are granted and whether each "
            "grant left an audit trail, the human-approval ledger (draft PRs "
            "an operator explicitly approved), the credential surface the AI "
            "can reach (GitHub scopes — never secrets), and the kill-switch "
            "state with what a flip would stop. Every number is computed "
            "deterministically from run telemetry, agent config, board "
            "metadata and connection rows. Strictly read-only — the kill "
            "switch itself is a human-only control this agent can report on "
            "but never touch."
        ),
        "capabilities": [
            "Summarize AI runs by dispatch source (chat vs detector) and tool calls by tool, agent and risk tier",
            "Report per-agent capability grants, power flags and their audit history (honestly flagging unaudited grants)",
            "Report the HITL ledger: draft PRs opened by explicit human approval",
            "Inventory the AI-reachable credentials (GitHub connections, repo allowlists) without exposing secrets",
            "Report the kill-switch state and what pausing AI would stop",
            "Compose the full AI-governance report from all five aggregates",
        ],
        "sample_prompts": [
            "What has the AI been doing this week?",
            "Which permissions does the AI have?",
            "Has anyone approved AI changes recently?",
            "Can we stop the AI right now?",
        ],
    }

    # ── Tools — 1:1 wrappers over ai_governance_service (deterministic, READ) ──

    @tool(
        name="get_ai_activity",
        description=(
            "AI-action ledger: deep runs by status and dispatch source (chat "
            "vs scheduled detector), plus tool calls counted by tool name, "
            "acting agent and risk tier (read / reversible_write / "
            'irreversible). Input: optional JSON {"window_days": 7}. '
            "Returns JSON with sample run ids as evidence."
        ),
        risk=ToolRisk.READ,
    )
    def get_ai_activity(self, input_str: str = "") -> str:
        window_days = _parse_window_days(input_str)
        try:
            data = ai_governance_service.ai_activity(self.workspace_id, window_days=window_days)
        except Exception:
            logger.exception("get_ai_activity failed workspace_id=%s", self.workspace_id)
            return "Could not compute AI activity — the run telemetry could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_capability_grants",
        description=(
            "Per-agent capability grants: which risk-gating capabilities "
            "(e.g. open_draft_pr) are enabled on each agent, the config "
            "flags that gate power (rubric_middleware, approval_granted, "
            "approval_required), and the audit history of grant changes. "
            "Agents whose grants predate auditing are flagged "
            "grant_history_recorded=false — report that honestly. No input. "
            "Returns JSON."
        ),
        risk=ToolRisk.READ,
    )
    def get_capability_grants(self, input_str: str = "") -> str:
        try:
            data = ai_governance_service.capability_grants(self.workspace_id)
        except Exception:
            logger.exception("get_capability_grants failed workspace_id=%s", self.workspace_id)
            return "Could not read the capability grants — agent config could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_hitl_ledger",
        description=(
            "Human-in-the-loop approval ledger: draft PRs opened by explicit "
            "operator approval (url, repo, branch, who approved, when). "
            "Denied approvals are NOT recorded by the platform — the tool "
            "says so; never present the absence of denials as zero denials. "
            'Input: optional JSON {"window_days": 30}. Returns JSON.'
        ),
        risk=ToolRisk.READ,
    )
    def get_hitl_ledger(self, input_str: str = "") -> str:
        window_days = _parse_window_days(input_str, default=_HITL_DEFAULT_WINDOW_DAYS)
        try:
            data = ai_governance_service.hitl_ledger(self.workspace_id, window_days=window_days)
        except Exception:
            logger.exception("get_hitl_ledger failed workspace_id=%s", self.workspace_id)
            return "Could not read the HITL ledger — board metadata could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_credential_inventory",
        description=(
            "Credential surface the AI can reach: GitHub connections with "
            "status, repo allowlist (the consent boundary), token PRESENCE "
            "as a boolean, and created/updated/last-used dates. Secret "
            "material is never included. No input. Returns JSON."
        ),
        risk=ToolRisk.READ,
    )
    def get_credential_inventory(self, input_str: str = "") -> str:
        try:
            data = ai_governance_service.credential_inventory(self.workspace_id)
        except Exception:
            logger.exception("get_credential_inventory failed workspace_id=%s", self.workspace_id)
            return "Could not read the credential inventory — connection rows could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_kill_switch_status",
        description=(
            "Kill-switch state: the workspace AI toggle "
            "(ai_teammate_enabled), the separate operator emergency flag, "
            "per-agent status rows, and what a pause would stop (active "
            "agents, in-flight deep runs, scheduled detector cycles). "
            "READ-ONLY — flipping the switch is a human-only action on the "
            "kill-switch endpoint, not something this agent can do. No "
            "input. Returns JSON."
        ),
        risk=ToolRisk.READ,
    )
    def get_kill_switch_status(self, input_str: str = "") -> str:
        try:
            data = ai_governance_service.kill_switch_status(self.workspace_id)
        except Exception:
            logger.exception("get_kill_switch_status failed workspace_id=%s", self.workspace_id)
            return "Could not read the kill-switch status — workspace state could not be read."
        return json.dumps(data, default=str)

    @tool(
        name="get_governance_report",
        description=(
            "Full AI-governance report composing AI activity, capability "
            "grants, the HITL ledger, the credential inventory and the "
            "kill-switch status into one JSON document. Input: optional "
            'JSON {"window_days": 7} (the HITL ledger keeps its own 30-day '
            "window). Returns JSON."
        ),
        risk=ToolRisk.READ,
    )
    def get_governance_report(self, input_str: str = "") -> str:
        window_days = _parse_window_days(input_str)
        try:
            data = ai_governance_service.governance_report(self.workspace_id, window_days=window_days)
        except Exception:
            logger.exception("get_governance_report failed workspace_id=%s", self.workspace_id)
            return "Could not compose the governance report — underlying governance data could not be read."
        return json.dumps(data, default=str)

    # ── System prompt: assessor-not-actor + honesty rules ────────────────

    def _build_system_message(self) -> str:
        base = super()._build_system_message()
        return base + (
            "\n\nAI-governance reporting rules (non-negotiable):\n"
            "- Answer ONLY from tool output. Every number, tool name, grant "
            "and URL you state must appear in a tool result from this "
            "conversation — never estimate, extrapolate, or fill gaps from "
            "memory.\n"
            "- You are an ASSESSOR, not an actor. You cannot pause, resume, "
            "grant, revoke, or approve anything. When asked to stop the AI "
            "or change a grant, report the current state and direct the "
            "operator to the kill-switch control in the HUD (or the "
            "capability settings) — a human must perform the action.\n"
            "- Always state the time window a number covers (the tools "
            "return window_days — repeat it).\n"
            "- When a section carries no_data=true, say plainly that there "
            "is no data yet for that dimension — never substitute a guess.\n"
            "- Honesty about gaps in the record is part of the report: when "
            "grant_history_recorded=false, say the grant predates auditing; "
            "when denials_recorded=false, say denials leave no trail — do "
            "NOT present either as 'zero events'.\n"
            "- Never output secret material. The tools only ever report "
            "token presence as a boolean; if asked for a token, scope, or "
            "ciphertext, refuse and point at the connection's settings "
            "page.\n"
            "- Risk tiers are the enforced ladder (read / reversible_write "
            "/ irreversible) — name the tier when reporting tool usage, and "
            "flag any irreversible-tier calls prominently."
        )

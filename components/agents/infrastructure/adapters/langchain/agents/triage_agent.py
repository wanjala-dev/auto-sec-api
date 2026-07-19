"""Security Triage Agent.

Triages incoming security signals — alerts, anomalies, log detections, cloud
findings (e.g. GuardDuty) — assesses severity, and files each as a task on the
SOC triage board, assigned to a team member. This takes alert fatigue off the
on-call analyst: instead of a raw firehose, the team gets prioritized, owned
work items.

Auto-discovered (ADR 0003) — no edits to base.py or any registry needed. Reuses
the existing task tools (create_task / assign_task / member discovery), so
findings land on the SAME Kanban board the frontend renders and the same
`Task.assigned_to` the operator sees.

Design note — agents require an ACTIVE workspace. The task tools' permission
check loads the workspace via the default (active-only) manager, so a freshly
onboarded workspace (which stays ``status != active`` until its own setup is
finished) cannot be triaged until it is activated. This is intentional:
workspace activation is an explicit step in the workspace's own setup, not
something the agent path relaxes. Do NOT "fix" this by widening the permission
check to inactive workspaces.
"""

import json

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.infrastructure.adapters.langchain.agents._mixins import (
    WorkspaceContextMixin,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    register_agent,
    tool,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    task_agent as task_tools,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    triage_agent as triage_tools,
)

_SEVERITIES = ("critical", "high", "medium", "low")


@register_agent(
    "triage_agent",
    aliases=("triage", "soc_triage", "security_triage"),
)
class TriageAgent(WorkspaceContextMixin, BaseAgent):
    """Triages security findings into prioritized, assigned SOC tasks."""

    profile = {
        "name": "Security Triage Agent",
        "summary": (
            "Triages incoming security signals (alerts, anomalies, log "
            "detections, cloud findings), assesses severity, and files each as "
            "a task on the SOC triage board assigned to a team member — taking "
            "alert fatigue off the on-call analyst."
        ),
        "capabilities": [
            "Assess a finding's severity (critical/high/medium/low)",
            "File a triaged finding as a task on the SOC Kanban board",
            "Assign findings to team members, balancing load",
            "Surface who is free to take new work",
            "List open findings on the board",
        ],
        "sample_prompts": [
            "Triage this alert: SSH brute force from 203.0.113.9 against auth-svc",
            "A GuardDuty finding shows unusual API calls from a new region — triage it and assign to whoever is free",
            "What findings are open on the board right now?",
        ],
    }

    @tool(
        name="list_pending_log_findings",
        description=(
            "List Log-Watch error findings on the SOC board that have not been "
            "triaged yet. No input. Returns JSON: [{task_id, title, service, "
            "level, signal}]. Call this first, then triage_finding on each."
        ),
        risk=ToolRisk.READ,
    )
    def list_pending_log_findings(self, input_str: str = "") -> str:
        return triage_tools.list_pending_log_findings(self, input_str)

    @tool(
        name="triage_finding",
        description=(
            "Triage one pending Log-Watch finding: look at the error, propose a "
            "grounded fix, post it as a comment on the card, and move the card "
            'into the Triage column. Input: JSON {"task_id": "<id>"} (or the '
            "bare task_id). Reversible — safe for autonomous runs."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def triage_finding(self, input_str: str) -> str:
        return triage_tools.triage_finding(self, input_str)

    @tool(
        name="record_finding",
        description=(
            "File a triaged security finding as a task on the SOC board and "
            "optionally assign it to a team member. Input: a JSON object with "
            "`severity` (critical|high|medium|low), `title` (short finding "
            "summary), optional `summary`/`description` (details, indicators, "
            "recommended action), and optional `assignee` (member name, email, "
            "or id). The task title is severity-tagged, e.g. '[HIGH] SSH brute "
            "force from 203.0.113.9'. Prefer assigning to a member returned by "
            "get_members_without_tasks to balance load."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def record_finding(self, input_str: str) -> str:
        raw = (input_str or "").strip()
        try:
            data = json.loads(raw) if raw.startswith("{") else {"title": raw}
        except (ValueError, TypeError):
            data = {"title": raw}

        title = (data.get("title") or "").strip()
        if not title:
            return "title is required to record a finding."

        severity = (data.get("severity") or "medium").strip().lower()
        if severity not in _SEVERITIES:
            severity = "medium"

        tagged_title = f"[{severity.upper()}] {title}"
        payload = {
            "title": tagged_title,
            "description": data.get("summary") or data.get("description") or "",
            "assignee": data.get("assignee"),
        }
        return task_tools.create_task(self, payload)

    @tool(
        name="get_team_members",
        description=(
            "List SOC team members in this workspace (name + id) so a finding can be assigned to a real person."
        ),
    )
    def get_team_members(self, input_str: str = "") -> str:
        return task_tools.get_team_members(self, input_str)

    @tool(
        name="get_members_without_tasks",
        description=(
            "List team members with no open tasks. Prefer these when assigning "
            "a new finding so on-call load stays balanced."
        ),
    )
    def get_members_without_tasks(self, input_str: str = "") -> str:
        return task_tools.get_members_without_tasks(self, input_str)

    @tool(
        name="assign_task",
        description=(
            "Assign an existing finding/task to a team member. Input: JSON with "
            "`task_id` (or `title` hint) and `assignee` (member name/email/id)."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def assign_task(self, input_str: str) -> str:
        return task_tools.assign_task(self, input_str)

    @tool(
        name="list_open_findings",
        description="List the open findings/tasks currently on the SOC board.",
    )
    def list_open_findings(self, input_str: str = "") -> str:
        return task_tools.list_workspace_tasks(self, input_str)

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
    asset_graph as asset_graph_tools,
)
from components.agents.infrastructure.adapters.langchain.tools import (
    ioc_enrichment as ioc_enrichment_tools,
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
        name="query_asset_graph",
        description=(
            "Ground blast-radius: look up a cloud resource in the asset graph. Input: an "
            "ARN, or a service / resource name or type to search. Returns JSON "
            '{"assets": [{arn, resource_type, exposure, region, account_id, service}]} — '
            "REAL exposure (public/internal/private), not a window-local guess. Use it "
            "when a finding names a cloud resource or service, before proposing a fix."
        ),
        risk=ToolRisk.READ,
    )
    def query_asset_graph(self, input_str: str = "") -> str:
        return asset_graph_tools.query_asset_graph(self, input_str)

    @tool(
        name="enrich_indicator",
        description=(
            "Enrich an indicator of compromise against threat intel to ground a verdict. "
            "Input: a single IP, domain, URL, or file hash (md5/sha1/sha256) — bare or "
            '{"indicator": "...", "provider": "virustotal"}. Returns JSON {verdict '
            "(malicious/suspicious/benign/unknown), score 0-100, positives, detail}. Use "
            "it when a finding names an external IP/domain/URL/hash, before proposing a fix."
        ),
        risk=ToolRisk.READ,
    )
    def enrich_indicator(self, input_str: str = "") -> str:
        return ioc_enrichment_tools.enrich_indicator(self, input_str)

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
        name="list_pending_cloud_exposure_findings",
        description=(
            "List cloud attack-path findings on the SOC board that have not been triaged "
            "yet. No input. Returns JSON: [{task_id, title, category, entry, target, "
            "risk_score}]. Call this first, then triage_cloud_exposure on each."
        ),
        risk=ToolRisk.READ,
    )
    def list_pending_cloud_exposure_findings(self, input_str: str = "") -> str:
        return triage_tools.list_pending_cloud_exposure_findings(self, input_str)

    @tool(
        name="triage_cloud_exposure",
        description=(
            "Triage one pending cloud attack-path finding: recommend how to break the "
            "toxic chain (a public asset reaching admin privileges or sensitive data), "
            "post it as a comment on the card, and move the card into the Triage column. "
            'Input: JSON {"task_id": "<id>"} (or the bare task_id). Reversible — safe for '
            "autonomous runs."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def triage_cloud_exposure(self, input_str: str) -> str:
        return triage_tools.triage_cloud_exposure(self, input_str)

    @tool(
        name="list_pending_container_vuln_findings",
        description=(
            "List Trivy container-image vulnerability (CVE) findings on the SOC board that "
            "have not been triaged yet. No input. Returns JSON: [{task_id, title, "
            "vulnerability_id, pkg_name, fixed_version}]. Call this first, then "
            "triage_container_vuln on each."
        ),
        risk=ToolRisk.READ,
    )
    def list_pending_container_vuln_findings(self, input_str: str = "") -> str:
        return triage_tools.list_pending_container_vuln_findings(self, input_str)

    @tool(
        name="triage_container_vuln",
        description=(
            "Triage one pending container-image CVE finding: recommend the package upgrade "
            "(or a mitigation when no fix exists), post it as a comment on the card, and "
            'move the card into the Triage column. Input: JSON {"task_id": "<id>"} (or the '
            "bare task_id). Reversible — safe for autonomous runs."
        ),
        risk=ToolRisk.REVERSIBLE_WRITE,
    )
    def triage_container_vuln(self, input_str: str) -> str:
        return triage_tools.triage_container_vuln(self, input_str)

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
        name="open_draft_pr",
        description=(
            "Open a DRAFT GitHub pull request that patches the file implicated "
            "by a triaged Log-Watch finding. Requires an installed GitHub "
            "connection (with the target repo on its allowlist) AND the triage "
            "agent's open_draft_pr capability enabled in its settings. Only "
            "works on findings that are already triaged and NOT flagged "
            "needs_human. Irreversible tier: needs explicit human approval; "
            "autonomous runs are denied and must surface the finding instead. "
            'Input: JSON {"task_id": "<id>", "repo": "<owner/repo>" (optional '
            "— defaults to the connection's first allowlisted repo)}."
        ),
        risk=ToolRisk.IRREVERSIBLE,
    )
    def open_draft_pr(self, input_str: str) -> str:
        return triage_tools.open_draft_pr(self, input_str)

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

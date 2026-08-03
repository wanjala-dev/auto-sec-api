"""AI-governance query service — deterministic read-only aggregation, no LLM.

The AI-SPM fact store from the vision doc
(``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md`` §3.4): what the AI
itself has been doing (runs, tool calls, risk tiers, dispatch sources), what
it is *allowed* to do (capability grants + the config flags that gate power),
the HITL ledger (draft PRs a human approved), the credential surface
(GitHubConnection scopes — NEVER token material), and the kill-switch state.
Every number is computed from rows that already exist — ``DeepRun`` /
``DeepRunLog`` telemetry, ``Agent.config``, board-finding metadata,
``GitHubConnection`` and ``Workspace.ai_teammate_enabled``. Nothing here
calls a model; the LLM in ``ai_governance_agent`` only narrates what these
functions return.

The three CROSS-context reads are routed through ports (app-layer ORM
burndown PR-6), never their persistence models: the HITL draft-PR ledger via
``project.TaskLookupPort``, the workspace kill-switch toggle via the agents
``WorkspaceQueryPort``, and the ``GitHubConnection`` credential surface via the
integrations ``GitHubConnectionStatusReadPort`` (which reduces the encrypted
token to a presence boolean INSIDE its adapter — the ciphertext never crosses
the port). Only this context's own ``ai.*`` reads remain inline (PR-10).

Hard rules (mirrors ``posture_service``, enforced by tests):

* **Read-only** — this module never writes. The kill-switch *actor* lives in
  ``application/use_cases/set_ai_kill_switch_use_case.py`` behind an
  owner/admin-gated endpoint; it is deliberately NOT an agent tool.
* **No secrets** — token ciphertext/plaintext never leaves the collector;
  only a boolean presence flag is reported.
* **Every claim carries its evidence** — ids and counts ride alongside every
  aggregate; missing data is explicit (``no_data`` flags / honest
  ``*_recorded: false`` notes), never invented. Where the platform does not
  record something (e.g. denied approvals), this module says so instead of
  fabricating an empty ledger that implies "zero denials happened".

Module style mirrors ``posture_service``: pure ``compute_*`` functions are
stdlib-only (plus the application-layer risk policy) and unit-testable
without a DB; the public entry points do their ORM reads through lazy
imports.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from components.agents.application.policies.tool_risk import ToolRisk, resolve_tool_risk

logger = logging.getLogger(__name__)

_MAX_SAMPLE_IDS = 10
_MAX_LEDGER_ITEMS = 20
_MAX_AUDIT_ENTRIES_PER_AGENT = 10

DISPATCH_SOURCE_CHAT = "chat"
DISPATCH_SOURCE_DETECTOR = "detector"

# Agent.config keys that gate power (beyond the capabilities map itself).
# ``rubric_middleware`` switches the deep-run verification loop;
# ``approval_granted`` unlocks irreversible-tier tools for a run;
# ``approval_required`` forces the HITL pause on every run.
_POWER_FLAG_KEYS = ("rubric_middleware", "approval_granted", "approval_required")

APPROVAL_DENIALS_NOTE = (
    "Denied approvals are not recorded anywhere today — only granted "
    "approvals (each opened draft PR) leave a trail. A denial leaves no row."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO timestamp defensively; naive values are assumed UTC.

    Same normalization as ``posture_service._parse_iso`` — live rows mix
    aware DB datetimes with naive ``datetime.now().isoformat()`` strings
    written into JSON metadata (fix #34), and a naive-aware comparison
    raises ``TypeError``.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ── Pure computations (no ORM, no Django) ───────────────────────────────────


def compute_ai_activity(
    run_rows: list[dict[str, Any]],
    tool_rows: list[dict[str, Any]],
    *,
    now: datetime,
    window_days: int,
) -> dict[str, Any]:
    """Aggregate the AI-action ledger for the window.

    Args:
        run_rows: one dict per ``DeepRun`` created in the window:
            ``{"id": str, "status": str,
               "source": "chat"|"detector"}`` (source pre-classified by the
            collector: a run whose user is the workspace's AI service
            principal was dispatched by the scheduled detector, anything
            else came from an interactive human).
        tool_rows: one dict per ``tool_observation`` DeepRunLog row in the
            window: ``{"agent_type": str, "tool_name": str,
            "risk": str|None}`` (risk pre-resolved by the collector from the
            ``@tool`` declaration, falling back to the central registry).

    Every count ships evidence (sample run ids); empty data → zeros +
    ``no_data``. ``agent_type`` is reported exactly as the telemetry
    recorded it (the agent class name) — never remapped or prettified.
    """
    runs_by_status: dict[str, int] = {}
    runs_by_source: dict[str, int] = {}
    for row in run_rows:
        status = str(row.get("status") or "unknown")
        runs_by_status[status] = runs_by_status.get(status, 0) + 1
        source = row.get("source")
        source = source if source in (DISPATCH_SOURCE_CHAT, DISPATCH_SOURCE_DETECTOR) else "unknown"
        runs_by_source[source] = runs_by_source.get(source, 0) + 1

    calls_by_tool: dict[str, int] = {}
    calls_by_agent: dict[str, int] = {}
    calls_by_risk: dict[str, int] = {}
    for row in tool_rows:
        tool_name = str(row.get("tool_name") or "unknown")
        agent = str(row.get("agent_type") or "unknown")
        risk = row.get("risk")
        risk = risk if risk in ToolRisk.ALL else resolve_tool_risk(tool_name)
        calls_by_tool[tool_name] = calls_by_tool.get(tool_name, 0) + 1
        calls_by_agent[agent] = calls_by_agent.get(agent, 0) + 1
        calls_by_risk[risk] = calls_by_risk.get(risk, 0) + 1

    return {
        "window_days": window_days,
        "computed_at": now.isoformat(),
        "runs": {
            "total": len(run_rows),
            "by_status": runs_by_status,
            "by_source": runs_by_source,
            "sample_run_ids": [str(r["id"]) for r in run_rows[:_MAX_SAMPLE_IDS]],
            "no_data": not run_rows,
        },
        "tool_calls": {
            "total": len(tool_rows),
            "by_tool": calls_by_tool,
            "by_agent": calls_by_agent,
            "by_risk_tier": calls_by_risk,
            "no_data": not tool_rows,
        },
        "no_data": not run_rows and not tool_rows,
    }


def compute_capability_grants(agent_rows: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    """Shape the per-agent capability/power-flag inventory.

    Args:
        agent_rows: one dict per ``Agent`` row in the workspace:
            ``{"agent_id": str, "agent_type": str, "status": str,
               "capabilities": dict, "power_flags": dict,
               "grant_audit_entries": [ {field_name, previous_value,
               new_value, actor_id, reason, created_at}, ... ]}``
            (audit entries collected read-only from the audit context).

    Honesty rule: an agent with zero audit entries for its grants is
    reported ``grant_history_recorded: false`` — the platform only began
    auditing capability PATCHes when the governance slice landed, so
    earlier grants have no trail and this module says so.
    """
    agents = []
    granted_total = 0
    audited_agents = 0
    for row in agent_rows:
        capabilities = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
        power_flags = row.get("power_flags") if isinstance(row.get("power_flags"), dict) else {}
        audit_entries = row.get("grant_audit_entries") or []
        enabled = sorted(key for key, value in capabilities.items() if value is True)
        granted_total += len(enabled)
        if audit_entries:
            audited_agents += 1
        agents.append(
            {
                "agent_id": str(row.get("agent_id")),
                "agent_type": str(row.get("agent_type") or "unknown"),
                "status": str(row.get("status") or "unknown"),
                "capabilities": capabilities,
                "enabled_capabilities": enabled,
                "power_flags": power_flags,
                "grant_history_recorded": bool(audit_entries),
                "grant_audit_entries": audit_entries[:_MAX_AUDIT_ENTRIES_PER_AGENT],
            }
        )

    return {
        "computed_at": now.isoformat(),
        "agents": agents,
        "agent_total": len(agents),
        "enabled_capability_total": granted_total,
        "agents_with_grant_history": audited_agents,
        "audit_note": (
            "Capability changes are audited from the governance slice onward; "
            "grants made before it have no recorded history."
        ),
        "no_data": not agent_rows,
    }


def compute_hitl_ledger(
    pr_rows: list[dict[str, Any]],
    *,
    now: datetime,
    window_days: int,
) -> dict[str, Any]:
    """The human-in-the-loop approval ledger for the window.

    Args:
        pr_rows: one dict per finding carrying a draft PR:
            ``{"task_id": str, "title": str, "url": str, "repo": str,
               "branch": str, "opened_by": str|None,
               "opened_at": iso str|datetime|None}``.

    Each opened draft PR IS a granted approval — the endpoint only fires on
    an explicit human click. Denials are honestly reported as not recorded
    (``APPROVAL_DENIALS_NOTE``); there is no row to count.
    ``opened_at`` values may be naive isoformat strings (they are written
    with ``datetime.now(UTC).isoformat()`` into JSON metadata) — parsing is
    naive/aware-safe. Rows with an unparseable ``opened_at`` are kept but
    never window-filtered in (they appear under ``undated``).
    """
    window_start = now - timedelta(days=window_days)
    in_window: list[dict[str, Any]] = []
    undated = 0
    for row in pr_rows:
        opened_at = _parse_iso(row.get("opened_at"))
        if opened_at is None:
            undated += 1
            continue
        if opened_at >= window_start:
            in_window.append(row)

    items = [
        {
            "task_id": str(r.get("task_id")),
            "title": str(r.get("title") or ""),
            "url": str(r.get("url") or ""),
            "repo": str(r.get("repo") or ""),
            "branch": str(r.get("branch") or ""),
            "opened_by": str(r["opened_by"]) if r.get("opened_by") else None,
            "opened_at": str(r.get("opened_at") or ""),
        }
        for r in in_window[:_MAX_LEDGER_ITEMS]
    ]

    return {
        "window_days": window_days,
        "computed_at": now.isoformat(),
        "draft_prs_opened": {
            "count": len(in_window),
            "items": items,
            "undated_records": undated,
            "no_data": not in_window,
        },
        "approvals": {
            "granted": len(in_window),
            "denials_recorded": False,
            "note": APPROVAL_DENIALS_NOTE,
        },
        "no_data": not pr_rows,
    }


def compute_credential_inventory(conn_rows: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    """Shape the credential surface the AI can reach. NO secret material.

    Args:
        conn_rows: one dict per ``GitHubConnection``:
            ``{"id": str, "name": str, "status": str,
               "repo_allowlist": list[str], "has_token": bool,
               "created_at": datetime, "updated_at": datetime,
               "last_used_at": datetime|None}``.

    The collector reduces the encrypted token to a presence boolean before
    this function ever sees the row — ciphertext/plaintext is structurally
    unreachable from here.
    """
    connections = []
    for row in conn_rows:
        created_at = _parse_iso(row.get("created_at"))
        updated_at = _parse_iso(row.get("updated_at"))
        last_used_at = _parse_iso(row.get("last_used_at"))
        allowlist = row.get("repo_allowlist") if isinstance(row.get("repo_allowlist"), list) else []
        connections.append(
            {
                "id": str(row.get("id")),
                "name": str(row.get("name") or ""),
                "status": str(row.get("status") or "unknown"),
                "repo_allowlist": [str(repo) for repo in allowlist],
                "repo_allowlist_count": len(allowlist),
                "has_token": bool(row.get("has_token")),
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "last_used_at": last_used_at.isoformat() if last_used_at else None,
            }
        )

    return {
        "computed_at": now.isoformat(),
        "github_connections": {
            "count": len(connections),
            "items": connections,
            "no_data": not connections,
        },
        "secrets_note": "Token material is never read into this report — presence is reported as a boolean only.",
        "no_data": not conn_rows,
    }


def compute_kill_switch_status(
    *,
    now: datetime,
    workspace_found: bool,
    ai_teammate_enabled: bool,
    emergency_flag_engaged: bool,
    teammate_profile: dict[str, Any] | None,
    agent_rows: list[dict[str, Any]],
    in_flight_deep_runs: int,
) -> dict[str, Any]:
    """The circuit-breaker state + what a flip would stop.

    ``ai_teammate_enabled`` is the workspace-level switch this slice makes
    first-class (``Workspace.ai_teammate_enabled`` — the value the
    entitlement gate, the chat gate and the detector fan-out all read).
    ``emergency_flag_engaged`` is the separate operator break-glass
    (``feature.ai_kill_switch``); both are reported so the operator sees the
    full stop-surface, not just the button they can reach.
    """
    agents_by_status: dict[str, int] = {}
    active_agents = 0
    agent_items = []
    for row in agent_rows:
        status = str(row.get("status") or "unknown")
        agents_by_status[status] = agents_by_status.get(status, 0) + 1
        if status == "active":
            active_agents += 1
        agent_items.append(
            {
                "agent_id": str(row.get("agent_id")),
                "agent_type": str(row.get("agent_type") or "unknown"),
                "status": status,
            }
        )

    return {
        "computed_at": now.isoformat(),
        "workspace_found": workspace_found,
        "ai_teammate_enabled": ai_teammate_enabled,
        "emergency_flag_engaged": emergency_flag_engaged,
        "ai_halted": (not ai_teammate_enabled) or emergency_flag_engaged,
        "teammate_profile": teammate_profile,
        "agents": {
            "total": len(agent_rows),
            "active": active_agents,
            "by_status": agents_by_status,
            "items": agent_items[:_MAX_SAMPLE_IDS],
            "no_data": not agent_rows,
        },
        "would_stop": {
            "active_agents": active_agents,
            "in_flight_deep_runs": in_flight_deep_runs,
            "scheduled_detector_cycles": ai_teammate_enabled,
        },
        "no_data": not workspace_found,
    }


# ── ORM-backed collectors (lazy imports, per posture_service conventions) ───


def _declared_tool_risks() -> dict[str, str]:
    """Map tool name → declared risk tier from every registered agent class.

    ``@tool(risk=...)`` declarations live on the agent classes; the central
    ``_TOOL_RISK`` registry only covers pre-decorator tools. Reading the
    registry keeps the reported tier identical to the tier the runtime gate
    enforces. Best-effort: a failure returns an empty map and the caller
    falls back to ``resolve_tool_risk`` (which defaults to ``read``).
    """
    try:
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        risks: dict[str, str] = {}
        for agent_class in {id(c): c for c in AgentRegistry._agents.values()}.values():
            for attr_name in dir(agent_class):
                try:
                    meta = getattr(getattr(agent_class, attr_name, None), "_agent_tool_meta", None)
                except Exception:  # pragma: no cover - defensive attr access
                    continue
                if isinstance(meta, dict) and meta.get("name"):
                    declared = meta.get("risk")
                    if declared in ToolRisk.ALL:
                        risks[str(meta["name"])] = declared
        return risks
    except Exception:
        logger.warning("declared tool-risk scan failed; falling back to the central registry", exc_info=True)
        return {}


def ai_activity(workspace_id: str, window_days: int = 7) -> dict[str, Any]:
    """Runs by source/status + tool calls by tool/agent/risk-tier in the window.

    The deep-run + tool-observation rows are the agents context's OWN ``ai.*``
    telemetry — read through its ``AiGovernanceReadPort`` seam (Rule 2). The
    source classification (detector vs chat) and risk-tier resolution stay HERE
    in the application layer off the raw rows the port returns."""
    from components.agents.application.providers.ai_provider import AIProvider

    now = _utc_now()
    window_start = now - timedelta(days=window_days)
    workspace_id = str(workspace_id)

    activity = AIProvider.build_ai_governance_read_port().collect_ai_activity(
        workspace_id=workspace_id, window_start=window_start
    )
    detector_user_ids = activity.service_user_ids

    run_rows: list[dict[str, Any]] = [
        {
            "id": row["id"],
            "status": row["status"],
            "source": (DISPATCH_SOURCE_DETECTOR if row["user_id"] in detector_user_ids else DISPATCH_SOURCE_CHAT),
        }
        for row in activity.run_rows
    ]

    declared_risks = _declared_tool_risks()
    tool_rows: list[dict[str, Any]] = []
    for row in activity.tool_rows:
        tool_name = row.get("tool_name") or "unknown"
        tool_rows.append(
            {
                "agent_type": row.get("agent_type") or "unknown",
                "tool_name": tool_name,
                "risk": declared_risks.get(tool_name) or resolve_tool_risk(tool_name),
            }
        )

    return compute_ai_activity(run_rows, tool_rows, now=now, window_days=window_days)


def capability_grants(workspace_id: str) -> dict[str, Any]:
    """Per-agent capability grants, power flags and their audit history.

    The ``Agent`` rows + their capability-grant audit history are agents-owned
    ``ai.*`` / audit reads — collected through the ``AiGovernanceReadPort`` seam
    (Rule 2). The pure ``compute_capability_grants`` still shapes the report off
    the returned rows."""
    from components.agents.application.providers.ai_provider import AIProvider

    now = _utc_now()
    agent_rows = AIProvider.build_ai_governance_read_port().collect_capability_agent_rows(
        workspace_id=str(workspace_id)
    )
    return compute_capability_grants(agent_rows, now=now)


def hitl_ledger(workspace_id: str, window_days: int = 30) -> dict[str, Any]:
    """Draft PRs opened by explicit human approval in the window.

    The ``project`` context owns the board ``Task``; the draft-PR findings are
    read through its inbound seam (``TaskLookupPort.list_draft_pr_findings``)
    instead of reaching into ``project``'s ORM from this application-layer
    service (Rule 2 / architecture-skill C3).
    """
    from components.project.application.providers.project_provider import ProjectProvider

    now = _utc_now()
    findings = ProjectProvider.build_task_lookup_port().list_draft_pr_findings(workspace_id=str(workspace_id))
    pr_rows = [
        {
            "task_id": str(finding.task_id),
            "title": finding.title,
            "url": finding.url,
            "repo": finding.repo,
            "branch": finding.branch,
            "opened_by": finding.opened_by,
            "opened_at": finding.opened_at,
        }
        for finding in findings
    ]

    return compute_hitl_ledger(pr_rows, now=now, window_days=window_days)


def credential_inventory(workspace_id: str) -> dict[str, Any]:
    """GitHub credential surface: presence, allowlist, dates. NO secrets.

    The ``integrations`` context owns ``GitHubConnection`` (which holds the
    encrypted PAT). Its credential surface is read through the integrations
    inbound seam (``GitHubConnectionStatusReadPort``) rather than this service
    reaching into ``integrations``' ORM (Rule 2 / architecture-skill C3). The
    adapter reduces ``token_ciphertext`` to a ``has_token`` boolean before it ever
    returns — the ciphertext is structurally unreachable from here.
    """
    from components.integrations.application.providers.github_connection_status_provider import (
        get_github_connection_status_reader,
    )

    now = _utc_now()
    statuses = get_github_connection_status_reader().list_statuses(workspace_id=str(workspace_id))
    conn_rows = [
        {
            "id": status.id,
            "name": status.name,
            "status": status.status,
            "repo_allowlist": status.repo_allowlist,
            # The port DTO carries only the presence boolean — never the token.
            "has_token": status.has_token,
            "created_at": status.created_at,
            "updated_at": status.updated_at,
            "last_used_at": status.last_used_at,
        }
        for status in statuses
    ]

    return compute_credential_inventory(conn_rows, now=now)


def kill_switch_status(workspace_id: str) -> dict[str, Any]:
    """Kill-switch state: workspace toggle, emergency flag, what would stop.

    The workspace toggle is read through the agents cross-context
    ``WorkspaceQueryPort`` (base manager, so an inactive workspace is still found);
    the agents-owned teammate profile + agent inventory + in-flight run count come
    through the ``AiGovernanceReadPort`` seam (Rule 2)."""
    from components.agents.application.policies.ai_kill_switch import is_ai_killed
    from components.agents.application.providers.ai_provider import AIProvider

    now = _utc_now()
    workspace_id = str(workspace_id)

    workspace_status = AIProvider.build_workspace_query().get_ai_toggle_status(workspace_id)
    inventory = AIProvider.build_ai_governance_read_port().collect_kill_switch_inventory(workspace_id=workspace_id)

    return compute_kill_switch_status(
        now=now,
        workspace_found=workspace_status.found,
        ai_teammate_enabled=workspace_status.ai_teammate_enabled,
        emergency_flag_engaged=bool(is_ai_killed(workspace_id)),
        teammate_profile=inventory.teammate_profile,
        agent_rows=inventory.agent_rows,
        in_flight_deep_runs=inventory.in_flight_deep_runs,
    )


def governance_report(workspace_id: str, window_days: int = 7) -> dict[str, Any]:
    """Compose all five governance aggregates into one report.

    ``hitl_ledger`` keeps its own longer default window (30 days) — approval
    events are sparse and a 7-day HITL slice would routinely read as empty.
    """
    return {
        "window_days": window_days,
        "ai_activity": ai_activity(workspace_id, window_days=window_days),
        "capability_grants": capability_grants(workspace_id),
        "hitl_ledger": hitl_ledger(workspace_id),
        "credential_inventory": credential_inventory(workspace_id),
        "kill_switch_status": kill_switch_status(workspace_id),
    }

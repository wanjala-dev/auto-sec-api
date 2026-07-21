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


def _ai_service_user_ids(workspace_id: str) -> set[str]:
    from infrastructure.persistence.ai.models import AITeammateProfile

    return {
        str(user_id)
        for user_id in AITeammateProfile.objects.filter(workspace_id=workspace_id).values_list("user_id", flat=True)
    }


def ai_activity(workspace_id: str, window_days: int = 7) -> dict[str, Any]:
    """Runs by source/status + tool calls by tool/agent/risk-tier in the window."""
    from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

    now = _utc_now()
    window_start = now - timedelta(days=window_days)
    workspace_id = str(workspace_id)

    detector_user_ids = _ai_service_user_ids(workspace_id)
    run_rows: list[dict[str, Any]] = []
    runs = DeepRun.objects.filter(workspace_id=workspace_id, created_at__gte=window_start).only(
        "id", "status", "user_id"
    )
    for run in runs.iterator(chunk_size=500):
        run_rows.append(
            {
                "id": str(run.id),
                "status": run.status,
                "source": (DISPATCH_SOURCE_DETECTOR if str(run.user_id) in detector_user_ids else DISPATCH_SOURCE_CHAT),
            }
        )

    declared_risks = _declared_tool_risks()
    tool_rows: list[dict[str, Any]] = []
    logs = DeepRunLog.objects.filter(
        deep_run__workspace_id=workspace_id,
        event_type="tool_observation",
        created_at__gte=window_start,
    ).only("id", "agent_type", "tool_name")
    for log in logs.iterator(chunk_size=500):
        tool_name = log.tool_name or "unknown"
        tool_rows.append(
            {
                "agent_type": log.agent_type or "unknown",
                "tool_name": tool_name,
                "risk": declared_risks.get(tool_name) or resolve_tool_risk(tool_name),
            }
        )

    return compute_ai_activity(run_rows, tool_rows, now=now, window_days=window_days)


def _grant_audit_entries(agent) -> list[dict[str, Any]]:
    """Read-only audit history for the agent's capability grants.

    Goes through the audit context's application provider (never its
    infrastructure directly). Best-effort: an audit read failure yields an
    empty history — reported as "not recorded", never invented.
    """
    try:
        from components.audit.application.providers.audit_log_provider import get_audit_log_provider

        entries = get_audit_log_provider().get_entity_history(
            instance=agent,
            field_name="capabilities",
            limit=_MAX_AUDIT_ENTRIES_PER_AGENT,
        )
    except Exception:
        logger.warning("capability grant audit read failed agent_id=%s", agent.agent_id, exc_info=True)
        return []
    rows = []
    for entry in entries:
        created_at = _parse_iso(getattr(entry, "created_at", None))
        rows.append(
            {
                "field_name": getattr(entry, "field_name", ""),
                "previous_value": getattr(entry, "previous_value", None),
                "new_value": getattr(entry, "new_value", None),
                "actor_id": getattr(entry, "actor_id", None),
                "actor_display": getattr(entry, "actor_display", ""),
                "reason": getattr(entry, "reason", ""),
                "created_at": created_at.isoformat() if created_at else None,
            }
        )
    return rows


def capability_grants(workspace_id: str) -> dict[str, Any]:
    """Per-agent capability grants, power flags and their audit history."""
    from infrastructure.persistence.ai.agents.models import Agent

    now = _utc_now()
    agent_rows: list[dict[str, Any]] = []
    agents = Agent.objects.filter(workspace_id=str(workspace_id)).only("agent_id", "agent_type", "status", "config")
    for agent in agents.iterator(chunk_size=500):
        config = agent.config if isinstance(agent.config, dict) else {}
        capabilities = config.get("capabilities") if isinstance(config.get("capabilities"), dict) else {}
        power_flags = {key: bool(config.get(key)) for key in _POWER_FLAG_KEYS if key in config}
        agent_rows.append(
            {
                "agent_id": str(agent.agent_id),
                "agent_type": agent.agent_type,
                "status": agent.status,
                "capabilities": capabilities,
                "power_flags": power_flags,
                "grant_audit_entries": _grant_audit_entries(agent),
            }
        )

    return compute_capability_grants(agent_rows, now=now)


def hitl_ledger(workspace_id: str, window_days: int = 30) -> dict[str, Any]:
    """Draft PRs opened by explicit human approval in the window."""
    from infrastructure.persistence.project.models import Task

    now = _utc_now()
    pr_rows: list[dict[str, Any]] = []
    tasks = Task.objects.filter(workspace_id=str(workspace_id), source_type__startswith="ai.").only(
        "id", "title", "metadata"
    )
    for task in tasks.iterator(chunk_size=500):
        meta = task.metadata if isinstance(task.metadata, dict) else {}
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        draft_pr = payload.get("draft_pr") if isinstance(payload.get("draft_pr"), dict) else {}
        if not draft_pr.get("url"):
            continue
        pr_rows.append(
            {
                "task_id": str(task.id),
                "title": task.title,
                "url": draft_pr.get("url"),
                "repo": draft_pr.get("repo"),
                "branch": draft_pr.get("branch"),
                "opened_by": draft_pr.get("opened_by"),
                "opened_at": draft_pr.get("opened_at"),
            }
        )

    return compute_hitl_ledger(pr_rows, now=now, window_days=window_days)


def credential_inventory(workspace_id: str) -> dict[str, Any]:
    """GitHub credential surface: presence, allowlist, dates. NO secrets."""
    from infrastructure.persistence.integrations.models import GitHubConnection

    now = _utc_now()
    conn_rows: list[dict[str, Any]] = []
    connections = GitHubConnection.objects.filter(workspace_id=str(workspace_id)).order_by("-created_at")
    for conn in connections.iterator(chunk_size=100):
        conn_rows.append(
            {
                "id": str(conn.id),
                "name": conn.name,
                "status": conn.status,
                "repo_allowlist": conn.repo_allowlist,
                # Reduced to a presence boolean HERE — ciphertext never
                # travels past this line (and is never logged).
                "has_token": bool(conn.token_ciphertext),
                "created_at": conn.created_at,
                "updated_at": conn.updated_at,
                "last_used_at": conn.last_used_at,
            }
        )

    return compute_credential_inventory(conn_rows, now=now)


def kill_switch_status(workspace_id: str) -> dict[str, Any]:
    """Kill-switch state: workspace toggle, emergency flag, what would stop."""
    from infrastructure.persistence.ai.agents.models import Agent, DeepRun
    from infrastructure.persistence.ai.models import AITeammateProfile

    now = _utc_now()
    workspace_id = str(workspace_id)

    workspace = None
    try:
        from infrastructure.persistence.workspaces.models import Workspace

        queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
        workspace = queryset.filter(id=workspace_id).first()
    except Exception:
        logger.exception("kill_switch_status workspace read failed workspace_id=%s", workspace_id)

    from components.agents.application.policies.ai_kill_switch import is_ai_killed

    profile = AITeammateProfile.objects.filter(workspace_id=workspace_id).first()
    teammate_profile = (
        {"status": profile.status, "is_enabled": bool(profile.is_enabled)} if profile is not None else None
    )

    agent_rows = [
        {"agent_id": str(agent.agent_id), "agent_type": agent.agent_type, "status": agent.status}
        for agent in Agent.objects.filter(workspace_id=workspace_id)
        .only("agent_id", "agent_type", "status")
        .iterator(chunk_size=500)
    ]
    in_flight = DeepRun.objects.filter(
        workspace_id=workspace_id, status__in=(DeepRun.STATUS_PENDING, DeepRun.STATUS_RUNNING)
    ).count()

    return compute_kill_switch_status(
        now=now,
        workspace_found=workspace is not None,
        ai_teammate_enabled=bool(getattr(workspace, "ai_teammate_enabled", False)),
        emergency_flag_engaged=bool(is_ai_killed(workspace_id)),
        teammate_profile=teammate_profile,
        agent_rows=agent_rows,
        in_flight_deep_runs=in_flight,
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

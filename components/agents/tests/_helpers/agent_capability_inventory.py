"""Canonical agent capability inventory — auto-sec fleet.

This module is the **contract** between every specialist agent and the
test suite. ``CANONICAL_TOOLS`` lists the exact set of tools each agent
must expose; ``test_agent_capability_inventory.py`` asserts every
agent's actual tools match this dict, byte-for-byte.

When you add a new tool to an agent, you MUST update the inventory in
the same change. The test fails loudly with a symmetric diff if you
don't — that is intentional. It forces an explicit decision: is this
tool the right agent's territory? Is the description sharp enough?

When you add a NEW agent class, append it to ``CANONICAL_TOOLS`` (with
its full tool set). ``test_agent_capability_inventory.py::
test_every_registered_specialist_has_an_inventory_entry`` fires if you
miss it.

Universal tools (``UNIVERSAL_TOOLS``) are tools the framework adds to
every agent through ``BaseAgent`` and the ``WorkspaceContextMixin``.
They are excluded from the cross-agent overlap check (Pattern D) and
must NOT be repeated in ``CANONICAL_TOOLS`` entries.

Shared tools (``SHARED_TOOLS``) are the deliberate exceptions to the
one-owner rule: the same implementation registered on a declared set of
agents (e.g. the triage agent wraps the task tools so a finding can be
filed and assigned without a second routing hop). Pattern D verifies
the actual overlap matches these declarations EXACTLY — an undeclared
collision still fails.

History:
- 2026-05-08 — created as part of the GTM lock-down (PR-A, wanjala).
- 2026-07 — rebuilt for the auto-sec fork: inventory now mirrors the
  actual registered fleet (workspace / task / project / user / triage /
  log_watch / optimization). The wanjala-only specialists (budget,
  grants, financial, sponsorship, sponsor, donation, fundraising, blog,
  writing, sharing, admin_verification) were never ported here and
  their entries were pure drift — every PR paid a "mine vs pre-existing"
  tax on their failures.
"""

from __future__ import annotations

# ── Universal tools provided by the framework ──────────────────────────
#
# ``retrieve_workspace_context`` is appended by ``BaseAgent._setup_tools``
# to every agent. ``whoami`` and ``get_workspace_info`` come from
# ``WorkspaceContextMixin`` — every specialist except ``workspace_agent``
# inherits the mixin (workspace_agent has its own organization tools and
# the mixin would shadow them).
#
# These tools live on multiple agents intentionally; the cross-agent
# overlap test allowlists them.
UNIVERSAL_TOOLS: frozenset[str] = frozenset(
    {
        "retrieve_workspace_context",
        "whoami",
        "get_workspace_info",
    }
)


# ── Deliberately shared tools ──────────────────────────────────────────
#
# tool name -> the EXACT set of agents allowed to register it. Every
# entry here is the SAME implementation (``task_tools``) exposed on both
# agents on purpose: the SOC triage flow files a finding as a task and
# assigns it in one hop, so the triage agent wraps the task agent's
# member-discovery + assignment tools rather than bouncing the planner
# through a second specialist mid-triage. Routing stays deterministic
# because both registrations delegate to the identical function.
#
# Adding a tool to this dict is a DELIBERATE decision — undeclared
# overlaps (or an overlap whose agent set differs from the declaration)
# still fail Pattern D.
SHARED_TOOLS: dict[str, frozenset[str]] = {
    "assign_task": frozenset({"task_agent", "triage_agent"}),
    "get_team_members": frozenset({"task_agent", "triage_agent"}),
    "get_members_without_tasks": frozenset({"task_agent", "triage_agent"}),
}


# ── Per-agent canonical tool sets ──────────────────────────────────────
#
# Each value is the set of tool names the agent's ``@tool`` decorators
# register. Universal tools (above) are NOT listed here; the inventory
# test computes the agent's actual tools and subtracts ``UNIVERSAL_TOOLS``
# before comparing. Shared tools ARE listed on every agent that
# registers them (the per-agent set is the agent's real surface).
CANONICAL_TOOLS: dict[str, set[str]] = {
    "workspace_agent": {
        "create_organization",
        "get_organization_info",
        "update_organization",
        "manage_organization_team",
        "get_organization_analytics",
        "manage_organization_categories",
        "manage_organization_tags",
        "get_organization_followers",
        "manage_organization_privacy",
        "get_organization_operations",
        "manage_organization_operations",
        "check_organization_permissions",
    },
    "task_agent": {
        "parse_task_request",
        "create_task",
        "break_down_task",
        "assign_task",
        "get_task_assignment",
        "get_team_members",
        "get_members_without_tasks",
        "get_projects",
        "list_workspace_tasks",
        "get_user_tasks",
        "get_due_tasks",
        "update_task_status",
        "update_task_due_date",
        "update_task_title",
        "delete_task",
        "add_task_comment",
        "list_task_comments",
        "start_task_timer",
        "stop_task_timer",
        "get_task_timer_status",
        "get_task_progress",
        "check_task_permissions",
    },
    "project_agent": {
        "create_project",
        "list_projects",
        "get_project_info",
        "update_project",
        "create_project_milestone",
        "update_project_milestone",
        "delete_project_milestone",
        "get_project_timeline",
        "assign_project_team",
        "create_project_task",
        "get_project_tasks",
        "manage_project_budget",
        "get_project_analytics",
        "generate_project_report",
        "check_project_permissions",
    },
    "user_agent": {
        # Workspace-member identity specialist. Aliases: ``user``,
        # ``users``, ``identity_agent``, ``identity``, ``members``.
        # Inherits ``whoami`` + ``get_workspace_info`` from
        # ``WorkspaceContextMixin`` — those live in the mixin column,
        # not here.
        "list_workspace_members",
        "search_workspace_members",
        "get_user_profile",
        "list_user_activity",
    },
    "triage_agent": {
        # SOC triage specialist. Aliases: ``triage``, ``soc_triage``,
        # ``security_triage``. Files findings on the SOC board, triages
        # pending log-watch findings, and (rung-1 HITL) opens draft PRs.
        # The three task tools are the deliberate SHARED_TOOLS overlap
        # with task_agent — see the declaration above.
        "list_open_findings",
        "list_pending_log_findings",
        "triage_finding",
        "record_finding",
        "open_draft_pr",
        "assign_task",
        "get_team_members",
        "get_members_without_tasks",
    },
    "log_watch_agent": {
        # Log anomaly specialist. Aliases: ``log_watch``, ``logwatch``,
        # ``log_monitor``. Read-only over recent log findings + suggests
        # fixes for the triage flow to act on.
        "list_recent_log_findings",
        "suggest_fix",
    },
    "optimization_agent": {
        # Log/cost optimization specialist. Aliases: ``optimization``,
        # ``log_optimizer``, ``log_optimization``. Surfaces pending
        # optimization advisories from the log analysis pipeline.
        "list_pending_optimizations",
        "advise_optimization",
    },
}


# ── Routing keyword expectations ───────────────────────────────────────
#
# Drives ``test_planner_routing_execution.py``: each entry is a goal
# string that must route to the named agent_type. Adding a new tool
# domain? Add at least one routing test entry too.
#
# The test uses ``RoutingMockLLM`` so this dict double-duties as both
# the routing rule (passed to the mock) and the assertion table.
#
# 2026-07 fork retune: entries for the unported wanjala specialists were
# deleted, and the SOC specialists (triage / log_watch / optimization) got
# entries. As of planner.system v9 (2026-07-19) the yaml routing table
# carries explicit SOC bullets for these keywords — the dynamic agent
# catalog from ``_build_agent_catalog()`` is now reinforcement, not the
# only backing. Keep this dict and the prompt's <routing_rules> in sync:
# a new tool domain gets a keyword here AND a routing bullet there.
ROUTING_EXPECTATIONS: dict[str, str] = {
    # task_agent
    "how many tasks": "task_agent",
    "list our tasks": "task_agent",
    "what's in todo": "task_agent",
    "assign those to me": "task_agent",
    "who is assigned to": "task_agent",
    "create a task": "task_agent",
    "tasks due today": "task_agent",
    "my tasks": "task_agent",
    "rename this task": "task_agent",
    "change the due date": "task_agent",
    "archive this task": "task_agent",
    "add a comment to": "task_agent",
    "list comments on": "task_agent",
    "start the timer on": "task_agent",
    "stop the timer on": "task_agent",
    "is the timer running on": "task_agent",
    "how much time have I tracked": "task_agent",
    # project_agent
    "list our projects": "project_agent",
    "how many projects": "project_agent",
    "project status": "project_agent",
    "project timeline": "project_agent",
    "create a project": "project_agent",
    "rename this project": "project_agent",
    "update the project description": "project_agent",
    "add a milestone": "project_agent",
    "delete the milestone": "project_agent",
    # workspace_agent
    "workspace overview": "workspace_agent",
    "list our followers": "workspace_agent",
    "engagement report": "workspace_agent",
    "invite a member": "workspace_agent",
    # user_agent — workspace member identity, profiles, per-user audit
    "list workspace members": "user_agent",
    "who is on the team": "user_agent",
    "what role does alice have": "user_agent",
    "search for the member named sarah": "user_agent",
    "show me bob's profile": "user_agent",
    "what has carol done recently": "user_agent",
    "find member aisha otieno": "user_agent",
    # triage_agent — SOC board triage, finding filing, draft-PR HITL
    "triage the pending findings": "triage_agent",
    "file a security finding": "triage_agent",
    "open a draft pr for this finding": "triage_agent",
    "assign the brute force finding to someone free": "triage_agent",
    # log_watch_agent — ingested log stream, anomalies, fix suggestions
    "watch the log stream for anomalies": "log_watch_agent",
    "what happened in the logs overnight": "log_watch_agent",
    "suggest a fix for that log error": "log_watch_agent",
    # optimization_agent — log noise / cost optimization advisories
    "any pending log optimizations": "optimization_agent",
    "how do we cut log noise": "optimization_agent",
}


__all__ = ["CANONICAL_TOOLS", "ROUTING_EXPECTATIONS", "SHARED_TOOLS", "UNIVERSAL_TOOLS"]

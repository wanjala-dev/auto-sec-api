"""Canonical agent capability inventory.

This module is the **contract** between every specialist agent and the
test suite. ``CANONICAL_TOOLS`` lists the exact set of tools each agent
must expose; ``test_agent_capability_inventory.py`` asserts every
agent's actual tools match this dict, byte-for-byte.

When you add a new tool to an agent, you MUST update the inventory in
the same change. The test fails loudly with a symmetric diff if you
don't — that is intentional. It forces an explicit decision: is this
tool the right agent's territory? Is the description sharp enough?

When you add a NEW agent class, append it to ``CANONICAL_TOOLS`` (with
its full tool set) AND make sure it's listed in
``components/agents/infrastructure/adapters/langchain/deep/llm_planner.py``
PER-TASK SPECIALIST ROUTING table. Both ``test_agent_capability_inventory.py``
and ``test_planner_agent_routing.py::test_every_registered_specialist_has_a_rule``
will fire if you miss either step.

Universal tools (``UNIVERSAL_TOOLS``) are tools the framework adds to
every agent through ``BaseAgent`` and the ``WorkspaceContextMixin``.
They are excluded from the cross-agent overlap check (Pattern D) and
must NOT be repeated in ``CANONICAL_TOOLS`` entries.

History:
- 2026-05-08 — created as part of the GTM lock-down (PR-A).
- See ``docs/plans/AGENT_TOOL_COVERAGE_AUDIT.md`` for the gap audit
  this enforces.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Set


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
UNIVERSAL_TOOLS: FrozenSet[str] = frozenset(
    {
        "retrieve_workspace_context",
        "whoami",
        "get_workspace_info",
    }
)


# ── Per-agent canonical tool sets ──────────────────────────────────────
#
# Each value is the set of tool names the agent's ``@tool`` decorators
# register. Universal tools (above) are NOT listed here; the inventory
# test computes the agent's actual tools and subtracts ``UNIVERSAL_TOOLS``
# before comparing.
#
# Add new tools by editing this dict in the same change that adds the
# ``@tool`` decorator. The test will tell you exactly what's missing
# or extra.
CANONICAL_TOOLS: Dict[str, Set[str]] = {
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
        "generate_organization_report",
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
        "create_project_from_prompt",
        "create_project_with_plan",
        "estimate_project_items",
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
        "get_project_spend",
        "manage_project_budget",
        "get_project_analytics",
        "generate_project_report",
        "check_project_permissions",
    },
    "budget_agent": {
        "create_budget",
        "update_budget",
        "list_budgets",
        "list_budget_categories",
        "add_budget_estimate",
        "update_estimate",
        "delete_estimate",
        "get_budget_summary",
        "compare_budget_actuals",
        "check_budget_permissions",
        "suggest_transaction_category",
        "reconcile_bank_export",
        "forecast_cash_flow",
        "draft_variance_narrative",
        # Added in the Sprint 6 unplanned-spend feature — surfaces a
        # recurring-expense template suggestion from a cluster of
        # unplanned transactions so the founder can promote one-off
        # spending into a budgeted line.
        "suggest_recurring_from_unplanned_pattern",
    },
    "grants_agent": {
        "list_grants",
        "get_grant",
        "create_grant",
        "transition_grant_stage",
        "record_grant_decision",
        "list_funders",
        "create_funder",
        "get_funder",
        "list_opportunities",
        "convert_opportunity_to_grant",
        "save_application_draft",
        "list_application_drafts",
        "submit_application_draft",
        "list_snippets",
        "save_snippet",
        "summarize_grant_pipeline",
        "summarize_upcoming_deadlines",
        "draft_loi_from_workspace_context",
        "draft_application_from_workspace_context",
        "recommend_funders_for_workspace",
        "search_grants_gov",
        "save_grant_search",
        "rank_opportunities_by_fit",
    },
    "financial_agent": {
        "parse_transaction",
        "create_expense",
        "create_income",
        "categorize_transaction",
        "list_transactions",
        "update_transaction",
        "delete_transaction",
        "get_top_expenses",
        "list_financial_reports",
        "get_financial_report",
        "generate_financial_report",
        "get_expense_status",
        "get_categories",
        "get_financial_summary",
        "compare_budget_spend",
        "validate_budget",
        "check_financial_permissions",
    },
    "sponsorship_agent": {
        "list_recipients",
        "list_sponsors",
        "get_child_info",
        "get_sponsor_info",
        "create_child_profile",
        "create_sponsor_profile",
        "create_sponsorship",
        "get_sponsorship_status",
        "update_child_progress",
        "update_recipient",
        "update_sponsor",
        "update_sponsorship_status",
        "cancel_sponsorship",
        "manage_sponsorship_goal",
        "get_sponsorship_analytics",
        "get_sponsorship_overview",
        "send_sponsor_update",
        "manage_sponsorship_payments",
        "check_sponsorship_permissions",
        "generate_sponsorship_report",
        "log_outreach",
        "list_outreach",
        "create_donation_link",
    },
    "sponsor_agent": {
        "my_giving_summary",
        "my_sponsorships",
        "my_donations",
    },
    "donation_agent": {
        "list_donors",
        "top_donors",
        "get_donor_info",
        "create_donation",
        "get_donation_history",
        "create_recurring_donation",
        "update_recurring_donation",
        "cancel_recurring_donation",
        "approve_donation",
        "reject_donation",
        "summarize_donations",
        "show_impact_reports",
        "create_donor_profile",
        "schedule_follow_up",
        "parse_donation_amount",
        "update_donor_info",
        "get_campaign_stats",
        "generate_donation_report",
        "check_donation_permissions",
    },
    "fundraising_agent": {
        "create_fundraising_campaign",
        "generate_fundraising_plan",
        "list_campaigns",
        "count_campaigns",
        "list_events",
        "get_event_info",
        "create_event",
        "update_event",
        "transition_event_lifecycle",
        "delete_event",
        "get_campaign_info",
        "update_campaign",
        "manage_campaign_goals",
        "get_campaign_donations",
        "get_campaign_analytics",
        "generate_fundraising_report",
        "manage_campaign_tags",
        "get_donor_analytics",
        "manage_recurring_donations",
        "manage_campaign_gallery",
        "get_campaign_performance",
        "check_fundraising_permissions",
    },
    "blog_agent": {
        "create_news_article",
        "get_news_article",
        "get_news_articles",
        "update_news_article",
        "publish_news_article",
        "schedule_news_article",
        "delete_news_article",
        "toggle_article_feature",
        "manage_news_categories",
        "manage_news_tags",
        "manage_article_comments",
        "get_article_engagement",
        "get_news_analytics",
        "generate_news_report",
        "draft_social_post",
        "queue_social_post_task",
        "check_news_permissions",
    },
    "user_agent": {
        # PR #277 — workspace-member identity specialist.  Aliases:
        # ``user``, ``users``, ``identity_agent``, ``identity``,
        # ``members``.  Inherits ``whoami`` + ``get_workspace_info``
        # from ``WorkspaceContextMixin`` — those live in the mixin
        # column, not here.
        "list_workspace_members",
        "search_workspace_members",
        "get_user_profile",
        "list_user_activity",
    },
    "writing_agent": {
        # PR #303 — Writing surface specialist. Aliases:
        # ``newsletter_agent``, ``letter_agent``, ``draft_agent``.
        # Drafts artifacts in the Workspace → Writing surface.
        # Newsletters land at ``status=ai_drafted`` for human review —
        # this agent never sends. Inherits ``whoami`` +
        # ``get_workspace_info`` from ``WorkspaceContextMixin``.
        #
        # AI drafting surface (this PR): every drafting tool now
        # persists a WritingDraft (ai_drafted=True, status=draft) and
        # emits a draft-card artifact through ``collect_artifact`` so
        # the chat bubble can render an "Open in Writing →" CTA.
        # Newsletter persistence stays on the Newsletter aggregate
        # (separate DRAFT → AI_DRAFTED → SENT lifecycle) and is
        # unchanged here. The five ``draft_*_update`` tools (entity-
        # scoped) require the planner to resolve the entity UUID
        # first via the specialist that owns it — see planner.system
        # v7's "Entity-update drafting" routing block.
        "draft_newsletter_from_period",
        "draft_letter",
        "draft_mission",
        "draft_recipient_update",
        "draft_project_update",
        "draft_event_update",
        "draft_campaign_update",
        "summarize_period",
        "generate_blog_post",
        "extract_key_points",
    },
    "sharing_agent": {
        # PR #270 — resource-level sharing specialist. Aliases:
        # ``share``, ``sharing``. Manages per-resource share grants
        # (budget / task / project / report / newsletter / blog) without
        # granting workspace membership. Read-only on shared-with-me,
        # mutating on owned-resource grants.
        "share_resource",
        "create_share_link",
        "list_shares_on",
        "list_my_shared_resources",
        "revoke_share",
        "change_share_role",
        "list_shared_resource_ids",
        "who_has_access_to",
    },
    "admin_verification_agent": {
        # PR #392 — admin identity-verification ("KYC") specialist.
        # Aliases: ``kyc``, ``admin_kyc``, ``admin_verification``,
        # ``verification``. Read-only by design — never approves or
        # rejects. Approval is a human-in-the-loop boundary handled by
        # platform staff via Django admin (SKILL.md §1 #11). Tools
        # surface what's pending review, who hasn't started, expiry
        # reminders.
        "get_my_verification_status",
        "list_unverified_admins",
        "list_pending_review",
        "list_rejected_verifications",
        "summarize_verification_stats",
        "list_expiring_id_documents",
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
ROUTING_EXPECTATIONS: Dict[str, str] = {
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
    # budget_agent
    "how many budgets": "budget_agent",
    "am I over budget": "budget_agent",
    "budget summary": "budget_agent",
    "rename the budget": "budget_agent",
    "update the estimate": "budget_agent",
    "delete the estimate": "budget_agent",
    "why is marketing over budget": "budget_agent",
    "explain the variance": "budget_agent",
    "narrate the budget gap": "budget_agent",
    # financial_agent
    "list transactions": "financial_agent",
    "what did we spend": "financial_agent",
    "top expenses": "financial_agent",
    "financial summary": "financial_agent",
    "list financial reports": "financial_agent",
    "show me our reports": "financial_agent",
    "generate a financial report": "financial_agent",
    "update this transaction": "financial_agent",
    "delete this transaction": "financial_agent",
    # sponsorship_agent
    "list recipients": "sponsorship_agent",
    "who are my recipients": "sponsorship_agent",
    "how many sponsors": "sponsorship_agent",
    "how many sponsorships": "sponsorship_agent",
    "how many active sponsorships": "sponsorship_agent",
    "sponsorship overview": "sponsorship_agent",
    "update the recipient": "sponsorship_agent",
    "cancel the sponsorship": "sponsorship_agent",
    "set a goal for the recipient": "sponsorship_agent",
    "sponsorship report": "sponsorship_agent",
    "high level report of our sponsorship": "sponsorship_agent",
    "generate a sponsorship report": "sponsorship_agent",
    "download sponsorship report": "sponsorship_agent",
    # donation_agent
    "list our donors": "donation_agent",
    "top donors": "donation_agent",
    "biggest donors": "donation_agent",
    "donations this week": "donation_agent",
    "approve donation": "donation_agent",
    "reject donation": "donation_agent",
    "review this donation": "donation_agent",
    "cancel the recurring donation": "donation_agent",
    "update the recurring amount": "donation_agent",
    "donation report": "donation_agent",
    "generate a donation report": "donation_agent",
    "download donation report": "donation_agent",
    # sponsor_agent — the donor/sponsor persona's OWN giving (first-person).
    # Distinct from donation_agent / sponsorship_agent (org-admin side);
    # phrases chosen so no other route's keyword is a substring of them.
    "where did my money go": "sponsor_agent",
    "what was spent on my behalf": "sponsor_agent",
    "show my giving impact": "sponsor_agent",
    "how much have i given": "sponsor_agent",
    # fundraising_agent
    "list campaigns": "fundraising_agent",
    "how many campaigns": "fundraising_agent",
    "active campaigns": "fundraising_agent",
    "create a campaign": "fundraising_agent",
    "campaign performance": "fundraising_agent",
    "list our events": "fundraising_agent",
    "do we have any events": "fundraising_agent",
    "what events do we have": "fundraising_agent",
    "create an event": "fundraising_agent",
    "schedule the gala": "fundraising_agent",
    "go live with the event": "fundraising_agent",
    "pause the event": "fundraising_agent",
    "end the event": "fundraising_agent",
    # workspace_agent
    "workspace overview": "workspace_agent",
    "list our followers": "workspace_agent",
    "engagement report": "workspace_agent",
    "invite a member": "workspace_agent",
    # 2026-05-09 — generic workspace-scoped report verbs.
    # ``workspace_agent.generate_organization_report`` now produces a
    # PDF artifact via the FinancialReport pipeline (variant=impact
    # default). Lock the routing so future prompt edits don't break
    # the user-visible "write impact report" → paperclip flow.
    "write impact report": "workspace_agent",
    "create an impact report": "workspace_agent",
    "generate an impact report": "workspace_agent",
    "annual report": "workspace_agent",
    "create the annual report": "workspace_agent",
    "create a pdf report": "workspace_agent",
    "write a workspace report": "workspace_agent",
    "generate a workspace summary": "workspace_agent",
    # blog_agent
    "list articles": "blog_agent",
    "publish an article": "blog_agent",
    "news analytics": "blog_agent",
    "delete this article": "blog_agent",
    "feature this article": "blog_agent",
    # grants_agent
    "find grants closing this month": "grants_agent",
    "what's our grant pipeline status": "grants_agent",
    "draft an LOI for the Gates Foundation": "grants_agent",
    "summarise grant deadlines": "grants_agent",
    "list funders": "grants_agent",
    "search grants gov": "grants_agent",
    # user_agent — workspace member identity, profiles, per-user audit
    "list workspace members": "user_agent",
    "who is on the team": "user_agent",
    "what role does alice have": "user_agent",
    "search for the member named sarah": "user_agent",
    "show me bob's profile": "user_agent",
    "what has carol done recently": "user_agent",
    # writing_agent — Writing surface: newsletters, letters, summaries, memos
    "draft a monthly newsletter": "writing_agent",
    "write a thank-you letter to acme foundation": "writing_agent",
    "summarize workspace activity for q1": "writing_agent",
    "draft a memo about the spring fundraiser": "writing_agent",
    # v6 qualified bare-find: explicit entity-type qualifier routes
    # straight to the matching specialist (no multi-route).
    "find member aisha otieno": "user_agent",
    "find donor henry wanjala": "donation_agent",
    "find sponsor michael wong": "sponsorship_agent",
    "find recipient priya sharma": "sponsorship_agent",
    # admin_verification_agent — workspace-admin KYC / identity review
    "start admin verification for jane": "admin_verification_agent",
    "review my admin verification": "admin_verification_agent",
    "approve admin verification": "admin_verification_agent",
    # sharing_agent — resource-level sharing across workspaces
    "share this budget with priya": "sharing_agent",
    "list shares on this report": "sharing_agent",
    "revoke share for henry": "sharing_agent",
}


__all__ = ["CANONICAL_TOOLS", "ROUTING_EXPECTATIONS", "UNIVERSAL_TOOLS"]

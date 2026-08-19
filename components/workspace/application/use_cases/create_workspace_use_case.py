"""Use case: Create a workspace via the API.

Orchestrates plan provisioning, scaffolding, and user profile activation
through the bootstrap port — the same infrastructure the management-command
bootstrap flow uses.

No Django imports — depends only on ports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from components.agents.application.facades.ai_teammate_facade import ensure_agents_board
from components.shared_platform.application.facades.feature_flags_facade import is_feature_enabled
from components.workflow.application.facades.ai_findings_workflow_facade import (
    ensure_ai_findings_workflow_binding,
)
from components.workspace.application.ports.workspace_bootstrap_port import WorkspaceBootstrapPort

logger = logging.getLogger(__name__)

# Per-user gate for the onboarding team-choice flow (teams/boards QA
# 2026-08-16 §c). OFF (default) → today's behavior exactly; ON → the caller's
# team_name / include_red_team inputs are honored.
ONBOARDING_TEAM_CHOICE_FLAG = "feature.onboarding_team_choice"


def _as_opt_in(value: Any) -> bool:
    """True only for an EXPLICIT boolean opt-in (JSON true, or its common
    string spellings). Anything else — None, absent, "false", 0 — is False:
    an opt-in must never be inferred."""
    if value is True:
        return True
    return str(value).strip().lower() in {"true", "1", "yes"}


@dataclass(frozen=True)
class CreateWorkspaceResult:
    workspace: Any
    default_team: Any
    budget: Any


class CreateWorkspaceUseCase:
    """Finalise a newly-persisted workspace: plans, scaffolding, owner context."""

    def __init__(self, bootstrap_port: WorkspaceBootstrapPort) -> None:
        self._bootstrap = bootstrap_port

    def execute(
        self,
        *,
        workspace: Any,
        owner: Any,
        seed_starter_pack: bool = False,
        team_name: str | None = None,
        include_red_team: Any = None,
    ) -> CreateWorkspaceResult:
        """Run post-creation setup on *workspace* owned by *owner*.

        Steps:
        1. Ensure subscription plans exist (Free / Basic / Pro).
        2. Assign the Free plan if workspace has none.
        3. Create default team + budget via scaffolding.
        4. Activate workspace/team context on the owner's profile.
        5. Ensure the owner follows the workspace.

        The nonprofit starter-pack auto-seed (sample sponsor / recipient /
        donation / transaction / draft report) was retired 2026-06-03 —
        the sample data confused real users into thinking their dashboard
        already had data. The seeder code is kept (used by demo bootstrap
        flows + tests) and can still be invoked explicitly by passing
        ``seed_starter_pack=True``, but it is no longer called from the
        signup path. New workspaces land on empty shelves; the user fills
        them with their own data.
        """
        self._bootstrap.ensure_subscription_plans()
        # Step 2 — bind the Free tier. This docstring has promised it since the
        # use case was written; the fork stripped the implementation, so every
        # workspace landed with plan = NULL, which ``EntitlementsResolver``
        # reads as UNLIMITED. Restored here so the paywall applies to a real
        # signup and not just to workspaces that once had a Stripe subscription.
        self._bootstrap.ensure_default_plan(workspace=workspace)

        # Teamspaces get a generic "General" home team ("Contributors" collided
        # with the Contributor persona/role — nav rework). Personal workspaces
        # keep the warmer "Family".
        default_team_title = "Family" if getattr(workspace, "sector_id", None) == "personal" else "General"

        # feature.onboarding_team_choice (per-user, default OFF): flag ON lets
        # the operator NAME the single home team and makes the Red Team an
        # explicit opt-in; flag OFF ignores both inputs — today's behavior
        # exactly (silent default title + auto Red Team, ADR 0007).
        team_title = default_team_title
        include_red = True
        if is_feature_enabled(ONBOARDING_TEAM_CHOICE_FLAG, user=owner):
            chosen = (team_name or "").strip()[:255]
            team_title = chosen or default_team_title
            include_red = _as_opt_in(include_red_team)

        default_team, budget = self._bootstrap.ensure_workspace_scaffolding(
            workspace=workspace,
            owner=owner,
            team_title=team_title,
            include_red_team=include_red,
        )

        # A new workspace is created 'inactive' (the model default) — activate it
        # so it's usable + visible in me/summary and the HUD from the first load.
        self._bootstrap.activate_workspace(workspace=workspace)

        self._bootstrap.finalize_owner_profile(
            owner=owner,
            workspace_id=workspace.id,
            active_team_id=default_team.id,
        )

        self._bootstrap.ensure_workspace_follower(
            workspace=workspace,
            user=owner,
        )

        # Eager-provision the AI agent team + 'AI Findings' Kanban so the
        # frontend can rely on a non-null ``agent_team_id`` in the workspace
        # summary from day 1. Idempotent. See
        # docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md.
        ensure_agents_board(workspace)

        # Phase 4 — also install the "AI Findings Accepted" workflow
        # binding so dragging an AI task into Accepted on the board
        # fires the workflow → TaskAcceptedFromBoard chain out of the
        # box. Idempotent; no-op when the system template hasn't been
        # seeded yet.
        ensure_ai_findings_workflow_binding(workspace)

        # Teamspace-only: provision the starter system workflows (e.g. receipt
        # accountability) so core automations work out of the box. Idempotent
        # and best-effort (the use case never raises), so a seeding failure
        # never aborts workspace creation. Personal spaces don't get them.
        if _is_teamspace(workspace):
            from components.workflow.application.use_cases.seed_workspace_starter_workflows_use_case import (
                SeedWorkspaceStarterWorkflowsUseCase,
            )

            SeedWorkspaceStarterWorkflowsUseCase().execute(workspace.id)

        # The nonprofit starter-pack seeder (sample sponsor / recipient /
        # donation / transaction / draft report) belonged to the nonprofit
        # domain and is not part of the security product. ``seed_starter_pack``
        # is retained for signature compatibility but is now a no-op.

        return CreateWorkspaceResult(
            workspace=workspace,
            default_team=default_team,
            budget=budget,
        )


def _is_teamspace(workspace: Any) -> bool:
    """True for teamspaces only (excludes personal workspaces)."""
    return (getattr(workspace, "workspace_type", "") or "").lower() == "teamspace"

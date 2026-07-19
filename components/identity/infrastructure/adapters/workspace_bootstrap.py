"""Workspace bootstrap helpers for user onboarding consistency."""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q

from components.agents.application.facades.ai_teammate_facade import ensure_agents_board
from components.shared_platform.application.facades.feature_flags_facade import is_feature_enabled
from components.workflow.application.facades.ai_findings_workflow_facade import (
    ensure_ai_findings_workflow_binding,
)
from components.workspace.application.facades.workspace_facade import (
    ensure_workspace_follower,
    ensure_workspace_scaffolding,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import Workspace

logger = logging.getLogger(__name__)


def should_bootstrap_workspace(user) -> bool:
    """Return True when onboarding state allows workspace auto-bootstrap."""
    if not user:
        return False
    return bool(getattr(user, "is_onboard_complete", False))


def ensure_user_workspace_context(
    user, *, create_if_missing: bool = False, workspace_name: str | None = None
) -> Workspace | None:
    """Ensure a user has a resolvable workspace and active profile context.

    ``workspace_name`` is the optional name the user chose during onboarding.
    It is only used when a workspace is actually created here; for an existing
    workspace it is ignored (renaming is a settings concern, not bootstrap).
    """
    if not user:
        return None

    workspace = _preferred_workspace_for_user(user)
    created = False

    if workspace is None and create_if_missing:
        workspace = _create_bootstrap_workspace(user, workspace_name=workspace_name)
        created = workspace is not None

    if workspace is None:
        return None

    _sync_profile_context(user, workspace, force_workspace=created)
    ensure_workspace_follower(workspace, user)
    return workspace


def _home_eligible_workspaces(user):
    """Workspaces that can serve as the user's home / landing context.

    Only owner / team-member / workspace-member relationships qualify. A
    *followed* org or a one-off *donation* surfaces in the user's
    "Supporting" list but is NOT a home — the user holds no seat inside it
    and most sections 403. Resolving a home from a follow-only relationship
    is what dropped supporters onto an org profile page they can't access
    (e.g. a Join-door onboarder who followed an org then completed
    onboarding). Mirrors get_related_workspaces_queryset() minus the
    follower and donor branches.
    """
    return Workspace.objects.filter(
        Q(workspace_owner=user) | Q(workspace_teams__members=user) | Q(memberships__user=user)
    ).distinct()


def _preferred_workspace_for_user(user) -> Workspace | None:
    workspaces = _home_eligible_workspaces(user).order_by("-created_at")
    return workspaces.first()


def _user_has_any_workspace(user) -> bool:
    """True if the user owns / is a team-member / is a member of ANY workspace,
    INCLUDING inactive ones (uses all_objects, unlike the active-only home-
    eligible query). Used to suppress a duplicate bootstrap workspace.
    """
    return (
        Workspace.objects.all_objects()
        .filter(Q(workspace_owner=user) | Q(workspace_teams__members=user) | Q(memberships__user=user))
        .exists()
    )


def _build_workspace_name(user, is_personal: bool) -> str:
    name_hint = (getattr(user, "first_name", "") or "").strip() or (getattr(user, "username", "") or "").strip()
    if name_hint:
        suffix = "Personal Workspace" if is_personal else "Workspace"
        return f"{name_hint}'s {suffix}"[:250]
    return "Personal Workspace" if is_personal else "Workspace"


def _create_bootstrap_workspace(user, workspace_name: str | None = None) -> Workspace | None:
    # Never mint a bootstrap workspace if the user already owns/belongs to ANY
    # workspace (including an inactive/just-created one). Onboarding creates the
    # user's workspace as "inactive" (its own setup is a separate in-app step)
    # and flips is_onboard_complete; the next hydration (me/summary, login) then
    # calls this — without this guard it would add a spurious SECOND, auto-named
    # default workspace. Guarding at the creation point covers every caller
    # (the ensure-context use case AND the identity adapter) in one place.
    if _user_has_any_workspace(user):
        return None

    # Personal workspaces are gated per-user by feature.personal_space
    # (globally off in prod). Without the flag every bootstrap mints a
    # teamspace.
    is_personal = is_feature_enabled("feature.personal_space", user=user)
    # "General" home team for teamspaces (was "Contributors" — collided with the
    # Contributor persona/role); "Family" for personal workspaces.
    team_title = "Family" if is_personal else "General"

    chosen_name = (workspace_name or "").strip()[:250]
    resolved_name = chosen_name or _build_workspace_name(user, is_personal)

    with transaction.atomic():
        workspace = Workspace.objects.create(
            workspace_name=resolved_name,
            workspace_type=Workspace.PERSONAL if is_personal else Workspace.TEAMSPACE,
            workspace_owner=user,
            status="active",
            is_active=True,
            privacy=Workspace.PRIVATE if is_personal else Workspace.PUBLIC,
        )
        team, _ = ensure_workspace_scaffolding(workspace, user, team_title=team_title)
        ensure_workspace_follower(workspace, user)
        _sync_profile_context(user, workspace, default_team=team, force_workspace=True)
        ensure_agents_board(workspace)
        ensure_ai_findings_workflow_binding(workspace)
        # Teamspace-only: provision the starter system workflows (e.g. receipt
        # accountability) so core automations work out of the box. Dispatched
        # AFTER commit so the workspace + owner membership are durable first,
        # and best-effort so a seeding failure never aborts onboarding.
        if not is_personal:
            workspace_id = workspace.id
            transaction.on_commit(lambda: _seed_starter_workflows_safe(workspace_id))
        return workspace


def _seed_starter_workflows_safe(workspace_id) -> None:
    """Best-effort starter-workflow seeding for a teamspace (never raises)."""
    try:
        from components.workflow.application.use_cases.seed_workspace_starter_workflows_use_case import (
            SeedWorkspaceStarterWorkflowsUseCase,
        )

        SeedWorkspaceStarterWorkflowsUseCase().execute(workspace_id)
    except Exception:
        logger.exception("starter_workflow_seed_failed workspace_id=%s", workspace_id)


def ensure_personal_workspace(user) -> Workspace | None:
    """Idempotently provision a user's private (personal-type) workspace.

    Returns the user's existing personal workspace if one already exists,
    otherwise mints one (private, team "Family"). Unlike the
    onboarding bootstrap this always forces the personal type — it is the
    reusable core for the per-user personal-space pilot, and is what the
    onboarding bootstrap will call once personal spaces auto-provision for
    everyone. Does NOT change the user's active workspace if they already have
    one (a teamspace stays active until the user switches to the private one).
    """
    if not user:
        return None

    existing = Workspace.objects.filter(workspace_owner=user, workspace_type=Workspace.PERSONAL).first()
    if existing:
        return existing

    with transaction.atomic():
        workspace = Workspace.objects.create(
            workspace_name=_build_workspace_name(user, True),
            workspace_type=Workspace.PERSONAL,
            workspace_owner=user,
            status="active",
            is_active=True,
            privacy=Workspace.PRIVATE,
        )
        team, _ = ensure_workspace_scaffolding(workspace, user, team_title="Family")
        ensure_workspace_follower(workspace, user)
        _sync_profile_context(user, workspace, default_team=team)
        ensure_agents_board(workspace)
        ensure_ai_findings_workflow_binding(workspace)
        return workspace


def _sync_profile_context(user, workspace, *, default_team: Team | None = None, force_workspace: bool = False) -> None:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    updates = []

    if force_workspace or not profile.active_workspace_id:
        if profile.active_workspace_id != workspace.id:
            profile.active_workspace_id = workspace.id
            updates.append("active_workspace_id")

    if not profile.active_team_id:
        team = default_team or (Team.objects.filter(workspace=workspace, members=user).order_by("id").first())
        if team and profile.active_team_id != team.id:
            profile.active_team_id = team.id
            updates.append("active_team_id")

    if updates:
        profile.save(update_fields=updates)

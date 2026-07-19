"""ORM-level AI permission grant and identity helpers.

Infrastructure service — all logic here touches the ORM directly.
Application-layer callers should import from the re-export shim at
``components.agents.application.facades.agent_permissions_facade``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from django.contrib.auth import get_user_model

if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserType

User = get_user_model()


# ── AI Grant / Identity Helpers ─────────────────────────────────────────


def ensure_ai_grant(
    workspace_id: str,
    principal_id: str,
    *,
    scope_type: str | None = None,
    scope_id: str | None = None,
    actions: list[str] | None = None,
) -> "AIPermissionGrant":
    """Idempotently ensure the AI_EXECUTOR grant for a workspace/principal."""
    from infrastructure.persistence.ai.models import AIPermissionGrant

    scope_type = scope_type or AIPermissionGrant.SCOPE_WORKSPACE
    actions = actions or ["*"]
    grant, _ = AIPermissionGrant.objects.get_or_create(
        workspace_id=workspace_id,
        principal_id=principal_id,
        role=AIPermissionGrant.ROLE_AI_EXECUTOR,
        scope_type=scope_type,
        scope_id=scope_id,
        defaults={"status": AIPermissionGrant.STATUS_ACTIVE, "actions": actions},
    )
    if grant.status != AIPermissionGrant.STATUS_ACTIVE:
        grant.status = AIPermissionGrant.STATUS_ACTIVE
        grant.save(update_fields=["status", "updated_at"])
    if actions and grant.actions != actions:
        grant.actions = actions
        grant.save(update_fields=["actions", "updated_at"])
    return grant


def ensure_ai_identity(workspace) -> tuple:
    """Ensure the AI teammate profile, user, and default grant exist; returns (profile, user)."""
    from components.agents.infrastructure.services.actions_service import get_ai_action_service

    service = get_ai_action_service()
    profile = service.ensure_teammate(workspace)
    ai_user = profile.user
    ensure_ai_grant(str(workspace.id), str(ai_user.id))
    try:
        from components.agents.application.policies.agent_entitlements import (
            ensure_workspace_agent_type,
            resolve_agent_type,
        )

        agent_type = resolve_agent_type("ai_teammate")
        if agent_type:
            ensure_workspace_agent_type(
                str(workspace.id),
                agent_type,
                is_enabled=True,
                updated_by=ai_user,
            )
    except Exception:  # pragma: no cover - best-effort
        pass
    return profile, ai_user


DEFAULT_AGENTS_TEAM_TITLE = "Agents"
DEFAULT_AI_TEAMMATE_ALIAS = "Orchestrator Agent"


def resolve_ai_teammate_alias(workspace) -> str:
    """Return the AI teammate's alias for *workspace*.

    The alias is the user-chosen ``display_name`` on
    ``AITeammateProfile`` — treat it as the single source of truth for how
    the assistant identifies across the app (chat header, task
    attribution, audit messages, LLM system prompt, Kanban team title).
    Falls back to ``DEFAULT_AI_TEAMMATE_ALIAS`` when unset.
    """
    from infrastructure.persistence.ai.models import AITeammateProfile

    profile = AITeammateProfile.objects.filter(workspace=workspace).first()
    alias = (getattr(profile, "display_name", None) or "").strip()
    return alias or DEFAULT_AI_TEAMMATE_ALIAS


def _resolve_agents_team_title(workspace) -> str:
    """Return the desired Agents team title for *workspace*.

    Mirrors the AI teammate's alias so the board feels like the user's
    assistant's workspace rather than a generic "Agents" bucket. Falls
    back to ``DEFAULT_AGENTS_TEAM_TITLE`` when no alias is set (distinct
    from the teammate's own default so a brand-new workspace with no
    alias shows "Agents" on the board but the assistant identifies as
    "Orchestrator Agent" in chat).
    """
    from infrastructure.persistence.ai.models import AITeammateProfile

    profile = AITeammateProfile.objects.filter(workspace=workspace).first()
    alias = (getattr(profile, "display_name", None) or "").strip()
    if alias:
        return alias[:255]
    return DEFAULT_AGENTS_TEAM_TITLE


def ensure_agents_team(workspace, ai_user: "UserType"):
    """Ensure the workspace's AI-agents team exists and is named after the alias.

    Idempotent. Finds the team by ``kind=AI_AGENTS`` (authoritative) with a
    title-based fallback for legacy rows that predate the ``kind`` field.
    Keeps the title synchronized with the teammate's ``display_name`` so
    renaming the AI assistant renames the team too.
    """
    from infrastructure.persistence.team.models import Team
    from infrastructure.persistence.subscription.models import Plan

    plan = Plan.objects.filter(is_default=True).first() or Plan.objects.first()
    if plan is None:
        plan = Plan.objects.create(
            title="Starter",
            limits={"max_projects_per_team": 1, "max_members_per_team": 10, "max_tasks_per_project": 50},
            price=0,
            is_default=True,
        )

    desired_title = _resolve_agents_team_title(workspace)

    team = (
        Team.objects.filter(
            workspace=workspace, kind=Team.Kind.AI_AGENTS, status=Team.ACTIVE
        )
        .order_by("created_at")
        .first()
    )
    if team is None:
        # Fallback: legacy rows seeded before ``kind`` existed were just
        # titled "Agents". Adopt one if present instead of creating a dup.
        team = (
            Team.objects.filter(
                workspace=workspace,
                title__iexact=DEFAULT_AGENTS_TEAM_TITLE,
                status=Team.ACTIVE,
            )
            .order_by("created_at")
            .first()
        )

    if team is None:
        team = Team.objects.create(
            workspace=workspace,
            title=desired_title,
            created_by=ai_user,
            plan=plan,
            status=Team.ACTIVE,
            privacy=Team.PRIVATE,
            kind=Team.Kind.AI_AGENTS,
        )
    else:
        updates: list[str] = []
        if team.kind != Team.Kind.AI_AGENTS:
            team.kind = Team.Kind.AI_AGENTS
            updates.append("kind")
        if team.title != desired_title:
            team.title = desired_title
            updates.append("title")
        if updates:
            team.save(update_fields=updates)
    if not team.members.filter(id=ai_user.id).exists():
        team.members.add(ai_user)
    return team


def ai_can(
    workspace_id: str,
    principal_id: Optional[str],
    action: str,
    resource: Optional[str] = None,
    *,
    scope_type: Optional[str] = None,
    scope_id: Optional[str] = None,
) -> bool:
    """Check whether principal has permission via AI grants.

    This complements existing owner/follower/team checks; callers should OR them.
    AI_EXECUTOR grants allow actions on workspace scope or a narrower scope match.
    """
    from infrastructure.persistence.ai.models import AIPermissionGrant

    if not principal_id:
        return False
    queryset = AIPermissionGrant.objects.filter(
        workspace_id=workspace_id,
        principal_id=principal_id,
        role=AIPermissionGrant.ROLE_AI_EXECUTOR,
        status=AIPermissionGrant.STATUS_ACTIVE,
    )
    if scope_type:
        scoped = queryset.filter(scope_type=scope_type)
        if scope_id:
            scoped = scoped.filter(scope_id=scope_id)
        queryset = queryset.filter(
            scope_type=AIPermissionGrant.SCOPE_WORKSPACE
        ) | scoped

    grants = list(queryset)
    for grant in grants:
        actions = grant.actions or []
        if "*" in actions or not actions:
            return True
        if action in actions:
            return True
    return False

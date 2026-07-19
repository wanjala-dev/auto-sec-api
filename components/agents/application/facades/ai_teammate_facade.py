"""Published API for AI teammate lifecycle operations.

Other bounded contexts (team, workspace, etc.) import from this facade
when they need to enable/disable AI teammates or query teammate state.

This is the agents context's **published language** for teammate ops —
the only module external contexts should import from.

Implementation lives in the infrastructure layer; this facade re-exports.
"""
from __future__ import annotations

from typing import Any, Optional

# Re-export the AI Findings board column names as part of the agents
# context's published language, so external contexts (e.g. sign_off's
# task materializer) can address the board's columns WITHOUT importing
# agents' infrastructure. Pure string constants — no ORM at import.
from components.agents.infrastructure.services.agents_board_service import (  # noqa: F401
    ACCEPTED,
    DISMISSED,
    SUGGESTED,
    UNDER_REVIEW,
)


def ensure_ai_identity(workspace: Any) -> tuple:
    """Ensure the AI teammate profile, user, and default grant exist.

    Returns ``(profile, ai_user)``.
    """
    from components.agents.infrastructure.services.agent_permissions_service import (
        ensure_ai_identity as _ensure,
    )

    return _ensure(workspace)


def ensure_agents_team(workspace: Any, ai_user: Any) -> Any:
    """Ensure an 'Agents' team exists and the AI user is a member."""
    from components.agents.infrastructure.services.agent_permissions_service import (
        ensure_agents_team as _ensure,
    )

    return _ensure(workspace, ai_user)


def ensure_agents_board(workspace: Any) -> Any:
    """Ensure the workspace's Agents team, 'AI Findings' project, and four
    columns exist.

    Idempotent — safe to call on workspace bootstrap and on every finding.
    Returns the ``AgentsBoard`` value object (team + project + columns).
    This is the canonical entry point for any context that needs to
    guarantee the agent team Kanban surface exists for a workspace.
    """
    from components.agents.infrastructure.services.agents_board_service import (
        ensure_agents_board as _ensure,
    )

    return _ensure(workspace)


def get_teammate_profile(workspace_id: str) -> Optional[Any]:
    """Return the AI teammate profile for a workspace, or None."""
    from components.agents.infrastructure.services.actions_service import (
        get_ai_action_service,
    )

    service = get_ai_action_service()
    return service.get_teammate(workspace_id)


def enable_teammate(workspace: Any) -> tuple:
    """Full enable: profile + grants + team + entitlement.

    Returns ``(profile, ai_user)``.
    """
    from components.agents.infrastructure.services.agent_entitlements import (
        ensure_workspace_agent_type,
        resolve_agent_type,
    )

    profile, ai_user = ensure_ai_identity(workspace)
    ensure_agents_team(workspace, ai_user)

    agent_type = resolve_agent_type("ai_teammate")
    if agent_type:
        ensure_workspace_agent_type(
            str(workspace.id),
            agent_type,
            is_enabled=True,
            updated_by=ai_user,
        )
    return profile, ai_user


def disable_teammate(workspace: Any) -> None:
    """Full disable: profile + grants + entitlement."""
    from datetime import datetime, timezone

    from infrastructure.persistence.ai.models import AIPermissionGrant

    from components.agents.infrastructure.services.agent_entitlements import (
        ensure_workspace_agent_type,
        resolve_agent_type,
    )

    profile = get_teammate_profile(str(workspace.id))
    if not profile:
        return

    if profile.is_enabled:
        profile.is_enabled = False
        profile.status = "disabled"
        profile.save(update_fields=["is_enabled", "status", "updated_at"])

    AIPermissionGrant.objects.filter(
        workspace=workspace, principal=profile.user
    ).update(
        status=AIPermissionGrant.STATUS_DISABLED,
        updated_at=datetime.now(timezone.utc),
    )

    agent_type = resolve_agent_type("ai_teammate")
    if agent_type:
        ensure_workspace_agent_type(
            str(workspace.id),
            agent_type,
            is_enabled=False,
            updated_by=profile.user,
        )

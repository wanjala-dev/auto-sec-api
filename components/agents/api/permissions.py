"""Centralized AI permission checks, DRF permissions, and helpers.

The DRF permission class ``AgentAIPermission`` lives here in the API layer
(a primary/driving adapter) because it depends on DRF and the HTTP request.

ORM-level grant/identity helpers are defined in the infrastructure service
``components.agents.infrastructure.services.agent_permissions_service``
and re-exported here for backward compatibility.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

# Re-export ORM helpers via the application-layer provider so this
# controller never imports the infrastructure service directly
# (enforced by ``test_controllers_do_not_import_concrete_adapters``).
from components.agents.application.providers.agent_permissions_provider import (
    get_agent_permissions_provider,
)
from components.membership.api.permissions import has_workspace_permission

# The two workspace-agent capability gates, named once so every
# agent surface asks the same question. ``view_agents`` is carried by
# every seeded role; ``manage_agents`` only by ``owner`` and ``admin``
# (``seed_workspace_roles``). Both resolve the workspace from the
# request (URL kwargs, then body, then query params).
CanViewWorkspaceAgents = has_workspace_permission("view_agents")
CanManageWorkspaceAgents = has_workspace_permission("manage_agents")


def ai_can(*args, **kwargs):
    return get_agent_permissions_provider().ai_can(*args, **kwargs)


def ensure_ai_grant(*args, **kwargs):
    return get_agent_permissions_provider().ensure_ai_grant(*args, **kwargs)


def ensure_ai_identity(*args, **kwargs):
    return get_agent_permissions_provider().ensure_ai_identity(*args, **kwargs)


def ensure_agents_team(*args, **kwargs):
    return get_agent_permissions_provider().ensure_agents_team(*args, **kwargs)


class AiKillSwitchPermission(BasePermission):
    """Gate for the workspace AI kill switch (``/ai/agents/kill-switch/``).

    Reads (GET — the status chip) require ``view_agents`` (every seeded
    role carries it); writes (POST — the flip itself) require
    ``manage_agents``, which only the ``owner`` and ``admin`` system roles
    hold — the same membership-permission mechanism the integrations
    endpoints use (``has_workspace_permission``). The workspace is resolved
    from the request body / query params by the membership permission base.
    """

    def has_permission(self, request, view):
        gate = CanViewWorkspaceAgents if request.method in SAFE_METHODS else CanManageWorkspaceAgents
        return gate().has_permission(request, view)


class PostureDashboardPermission(BasePermission):
    """Gate for the posture dashboard (``/ai/agents/posture/dashboard/``).

    Read-only surface: every seeded member role carries ``view_agents``,
    so any active workspace member may read the dashboard — same
    membership-permission mechanism as the kill-switch GET. Non-members
    (and anonymous requests) are refused; the workspace is resolved from
    the query params by the membership permission base.
    """

    def has_permission(self, request, view):
        return CanViewWorkspaceAgents().has_permission(request, view)


class AgentAIPermission(BasePermission):
    """
    AI-specific permission checks.

    - ai_manage: settings/customization/disable/share.
    - ai_execute: execute/pause/resume.
    - ai_engage: follow/like/rate/comment.
    """

    def has_object_permission(self, request, view, obj):
        from components.agents.application.providers.ai_models_provider import get_ai_models_provider

        Agent = get_ai_models_provider().Agent
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_member,
        )

        agent = obj if isinstance(obj, Agent) else getattr(obj, "agent", None)
        if not agent or not request.user or not request.user.is_authenticated:
            return False

        user = request.user
        if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
            return True

        # Agent owner
        if str(agent.user_id) == str(user.id):
            return True

        workspace = agent.workspace
        if workspace and user_is_workspace_member(user, workspace):
            return True

        # Fallback to explicit permissions if granted
        if view and getattr(view, "required_ai_perm", None):
            perm_code = f"ai.{view.required_ai_perm}"
            return user.has_perm(perm_code)

        return False

    def has_permission(self, request, view):
        # For SAFE methods allow if authenticated; object-level will further restrict.
        if request.method in SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return request.user and request.user.is_authenticated


__all__ = [
    "AgentAIPermission",
    "AiKillSwitchPermission",
    "CanManageWorkspaceAgents",
    "CanViewWorkspaceAgents",
    "PostureDashboardPermission",
    "ai_can",
    "ensure_agents_team",
    "ensure_ai_grant",
    "ensure_ai_identity",
]

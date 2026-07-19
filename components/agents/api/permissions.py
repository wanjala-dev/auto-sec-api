"""Centralized AI permission checks, DRF permissions, and helpers.

The DRF permission class ``AgentAIPermission`` lives here in the API layer
(a primary/driving adapter) because it depends on DRF and the HTTP request.

ORM-level grant/identity helpers are defined in the infrastructure service
``components.agents.infrastructure.services.agent_permissions_service``
and re-exported here for backward compatibility.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission, SAFE_METHODS

# Re-export ORM helpers via the application-layer provider so this
# controller never imports the infrastructure service directly
# (enforced by ``test_controllers_do_not_import_concrete_adapters``).
from components.agents.application.providers.agent_permissions_provider import (
    get_agent_permissions_provider,
)


def ai_can(*args, **kwargs):
    return get_agent_permissions_provider().ai_can(*args, **kwargs)


def ensure_ai_grant(*args, **kwargs):
    return get_agent_permissions_provider().ensure_ai_grant(*args, **kwargs)


def ensure_ai_identity(*args, **kwargs):
    return get_agent_permissions_provider().ensure_ai_identity(*args, **kwargs)


def ensure_agents_team(*args, **kwargs):
    return get_agent_permissions_provider().ensure_agents_team(*args, **kwargs)


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
    "ai_can",
    "ensure_ai_grant",
    "ensure_ai_identity",
    "ensure_agents_team",
]

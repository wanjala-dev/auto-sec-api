"""Adapter implementing AgentPermissionPort via the application facades."""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_permission_port import AgentPermissionPort


class AgentPermissionAdapter(AgentPermissionPort):
    """Delegates to the existing application-layer permission facades.

    This adapter is the *only* place that imports directly from the
    application facades — callers in the infrastructure adapter layer
    depend on ``AgentPermissionPort`` instead.
    """

    def can_perform(
        self,
        *,
        agent_id: str,
        action_slug: str,
        workspace_id: str,
        user_id: str | None = None,
    ) -> bool:
        from components.agents.application.facades.agent_permissions_facade import ai_can

        # ai_can expects (agent_obj, action_slug, workspace_obj)
        # We resolve those from IDs lazily.
        from infrastructure.persistence.ai.agents.models import Agent

        agent = Agent.objects.filter(agent_id=agent_id).first()
        if agent is None:
            return False

        from infrastructure.persistence.workspaces.models import Workspace

        workspace = Workspace.objects.filter(id=workspace_id).first()
        if workspace is None:
            return False

        return ai_can(agent, action_slug, workspace)

    def ensure_ai_identity(self, *, workspace_id: str) -> Any:
        from components.agents.application.facades.agent_permissions_facade import (
            ensure_ai_identity as _ensure,
        )

        return _ensure(workspace_id)

    def ensure_agents_team(self, *, workspace_id: str) -> Any:
        from components.agents.application.facades.agent_permissions_facade import (
            ensure_agents_team as _ensure,
        )

        return _ensure(workspace_id)

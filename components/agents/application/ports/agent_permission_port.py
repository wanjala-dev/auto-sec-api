"""Port for agent-level permission checks.

Every LangChain tool file currently imports ``ai_can`` directly from the
application permissions facade and ``ensure_ai_identity``/``ensure_agents_team``
from the agent permissions facade.  This port abstracts those calls so the
adapter layer never imports application-layer policy code directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentPermissionPort(ABC):
    """Runtime permission gate for agent operations."""

    @abstractmethod
    def can_perform(
        self,
        *,
        agent_id: str,
        action_slug: str,
        workspace_id: str,
        user_id: str | None = None,
    ) -> bool:
        """Return *True* if *agent_id* is allowed to execute *action_slug*
        within *workspace_id*.

        This replaces direct calls to ``ai_can(agent, action_slug, workspace)``.
        """
        ...

    @abstractmethod
    def ensure_ai_identity(self, *, workspace_id: str) -> Any:
        """Guarantee that the AI system user exists in *workspace_id*.

        Returns the AI user object.  Creates one if it does not exist.
        """
        ...

    @abstractmethod
    def ensure_agents_team(self, *, workspace_id: str) -> Any:
        """Guarantee that the default AI-agents team exists in *workspace_id*.

        Returns the team object.  Creates one if it does not exist.
        """
        ...

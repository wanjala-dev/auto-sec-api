"""Port for the agent execution service — abstracts apps.ai.agents.service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentServicePort(ABC):
    """Thin abstraction over the agent service so the use case stays framework-free."""

    @abstractmethod
    def is_valid_agent_type(self, agent_type: str) -> bool: ...

    @abstractmethod
    def get_or_create_agent(
        self,
        *,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        config: dict,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def create_agent(
        self,
        *,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        config: dict,
        department_id: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def execute_agent(
        self,
        agent_id: str,
        query: str,
        *,
        performed_by: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def get_agent(self, agent_id: str) -> Any | None: ...

    @abstractmethod
    def pause_agent(self, agent_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def resume_agent(self, agent_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def remove_agent(self, agent_id: str) -> bool: ...

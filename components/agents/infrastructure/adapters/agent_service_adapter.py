"""Infrastructure adapter wrapping apps.ai.agents.service for the AgentServicePort."""

from __future__ import annotations

from typing import Any

from components.agents.infrastructure.services.agents_service import get_agent_service
from components.agents.application.ports.agent_service_port import AgentServicePort


class AgentServiceAdapter(AgentServicePort):
    """Thin delegation to the existing AgentService singleton."""

    def __init__(self) -> None:
        self._service = get_agent_service()

    def is_valid_agent_type(self, agent_type: str) -> bool:
        return self._service.is_valid_agent_type(agent_type)

    def get_or_create_agent(
        self,
        *,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        config: dict,
    ) -> dict[str, Any]:
        return self._service.get_or_create_agent(
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            config=config,
        )

    def create_agent(
        self,
        *,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        config: dict,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        return self._service.create_agent(
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            config=config,
            department_id=department_id,
        )

    def execute_agent(
        self,
        agent_id: str,
        query: str,
        *,
        performed_by: str,
    ) -> dict[str, Any]:
        return self._service.execute_agent(
            agent_id,
            query,
            performed_by=performed_by,
        )

    def get_agent(self, agent_id: str) -> Any | None:
        return self._service.get_agent(agent_id)

    def pause_agent(self, agent_id: str) -> dict[str, Any]:
        agent = self._service.get_agent(agent_id)
        if agent is None:
            return {}
        agent.pause()
        # Sync ORM state
        from infrastructure.persistence.ai.agents.models import Agent

        Agent.objects.filter(agent_id=agent_id).update(status="paused")
        return agent.get_state()

    def resume_agent(self, agent_id: str) -> dict[str, Any]:
        agent = self._service.get_agent(agent_id)
        if agent is None:
            return {}
        agent.resume()
        from infrastructure.persistence.ai.agents.models import Agent

        Agent.objects.filter(agent_id=agent_id).update(status="active")
        return agent.get_state()

    def remove_agent(self, agent_id: str) -> bool:
        return self._service.remove_agent(agent_id)

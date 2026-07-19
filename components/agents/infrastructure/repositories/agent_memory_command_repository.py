"""ORM adapter for agent memory write commands.

Extracted from agents_controller.py clear_agent_memory and
add_agent_system_message.
"""
from __future__ import annotations

from components.agents.domain.errors import (
    AgentNotFoundError,
    AgentPermissionError,
)
from components.agents.application.ports.agent_memory_command_port import (
    AddSystemMessageCommand,
    AddSystemMessageResult,
    AgentMemoryCommandPort,
    ClearMemoryCommand,
    ClearMemoryResult,
)


class OrmAgentMemoryCommandRepository(AgentMemoryCommandPort):

    @staticmethod
    def _get_agent(agent_id: str):
        from components.agents.infrastructure.services.agents_service import get_agent_service
        factory = get_agent_service()
        agent = factory.get_agent(agent_id)
        if not agent:
            raise AgentNotFoundError("Agent not found")
        return agent

    @staticmethod
    def _check_ownership(agent, user_id: str) -> None:
        if agent.user_id != user_id:
            raise AgentPermissionError("Permission denied")

    def clear_memory(self, *, command: ClearMemoryCommand) -> ClearMemoryResult:
        agent = self._get_agent(command.agent_id)
        self._check_ownership(agent, command.user_id)
        agent.clear_memory()
        return ClearMemoryResult(
            agent_id=command.agent_id,
            message="Agent memory cleared successfully",
        )

    def add_system_message(self, *, command: AddSystemMessageCommand) -> AddSystemMessageResult:
        from components.agents.domain.errors import AgentEngagementError

        agent = self._get_agent(command.agent_id)
        self._check_ownership(agent, command.user_id)
        if not command.content:
            raise AgentEngagementError("content is required")
        agent.add_system_message(command.content)
        return AddSystemMessageResult(
            agent_id=command.agent_id,
            content=command.content,
            message="System message added successfully",
        )

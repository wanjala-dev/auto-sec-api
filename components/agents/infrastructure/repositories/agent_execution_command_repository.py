"""ORM adapter for agent execution command operations.

Extracted from agents_controller.py execute_agent endpoint.
"""
from __future__ import annotations

from components.agents.domain.errors import (
    AgentDisabledError,
    AgentNotFoundError,
    AgentPermissionError,
)
from components.agents.application.ports.agent_execution_command_port import (
    AgentExecutionCommandPort,
    ExecuteAgentCommand,
    ExecuteAgentResult,
)


class OrmAgentExecutionCommandRepository(AgentExecutionCommandPort):

    def execute_agent(self, *, command: ExecuteAgentCommand) -> ExecuteAgentResult:
        from infrastructure.persistence.ai.agents.models import Agent
        from components.agents.infrastructure.services.agents_service import get_agent_service

        agent_record = (
            Agent.objects.select_related("profile", "workspace")
            .filter(agent_id=command.agent_id)
            .first()
        )
        if not agent_record:
            raise AgentNotFoundError("Agent not found")

        profile = getattr(agent_record, "profile", None)
        if profile and profile.is_disabled:
            raise AgentDisabledError("Agent is disabled")

        factory = get_agent_service()

        try:
            execution = factory.execute_agent_async(
                agent_id=command.agent_id,
                query=command.query,
                user_id=command.user_id,
            )
        except PermissionError as exc:
            raise AgentPermissionError(str(exc)) from exc

        memory_service = factory.get_agent_memory_service(command.agent_id)
        conversation_id = None
        try:
            conversation_id = memory_service.get_conversation_id()
        except Exception:
            conversation_id = None

        return ExecuteAgentResult(
            agent_id=command.agent_id,
            execution_id=execution.id,
            task_id=execution.task_id,
            status=execution.status,
            progress=execution.progress,
            state=execution.state,
            conversation_id=conversation_id,
        )

"""Use cases for agent lifecycle operations (create, pause, resume).

Extracts validation + state-transition logic from ``agents_controller``.
Framework-free — no Django, DRF, or ORM imports.

Each use case implements ``CommandHandler`` so it can be registered
with the shared-kernel Command Bus.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.commands.agent_lifecycle_command import (
    AgentStateCommand,
    AgentStateFailure,
    AgentStateSuccess,
    CreateAgentCommand,
    CreateAgentFailure,
    CreateAgentSuccess,
    DeleteAgentCommand,
    DeleteAgentFailure,
    DeleteAgentSuccess,
)
from components.agents.application.ports.agent_service_port import AgentServicePort
from components.shared_kernel.application.handlers import CommandHandler


CreateAgentResult = CreateAgentSuccess | CreateAgentFailure
AgentStateResult = AgentStateSuccess | AgentStateFailure
DeleteAgentResult = DeleteAgentSuccess | DeleteAgentFailure


class CreateAgentUseCase(CommandHandler[CreateAgentCommand]):
    """Validate agent type → create agent via service port."""

    def __init__(self, *, agent_service: AgentServicePort) -> None:
        self._agent_service = agent_service

    def handle(self, command: CreateAgentCommand) -> Any:
        return self.execute(command)

    def execute(self, command: CreateAgentCommand) -> CreateAgentResult:
        if not self._agent_service.is_valid_agent_type(command.agent_type):
            return CreateAgentFailure(
                error=f"Unsupported agent type: {command.agent_type}",
                status_code=400,
            )

        try:
            agent_info = self._agent_service.create_agent(
                agent_type=command.agent_type,
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                config=command.config,
                department_id=command.department_id,
            )
        except PermissionError as exc:
            return CreateAgentFailure(error=str(exc), status_code=403)
        except Exception as exc:
            return CreateAgentFailure(error=str(exc), status_code=500)

        return CreateAgentSuccess(agent_info=agent_info)


class AgentStateUseCase(CommandHandler[AgentStateCommand]):
    """Pause or resume an agent — validates ownership + disabled state."""

    def __init__(self, *, agent_service: AgentServicePort) -> None:
        self._agent_service = agent_service

    def handle(self, command: AgentStateCommand) -> Any:
        return self.execute(command)

    def execute(self, command: AgentStateCommand) -> AgentStateResult:
        agent = self._agent_service.get_agent(command.agent_id)
        if agent is None:
            return AgentStateFailure(error="Agent not found", status_code=404)

        # Ownership check
        if getattr(agent, "user_id", None) != command.user_id:
            return AgentStateFailure(error="Permission denied", status_code=403)

        if command.action == "pause":
            state = self._agent_service.pause_agent(command.agent_id)
            return AgentStateSuccess(message="Agent paused successfully", state=state)

        if command.action == "resume":
            state = self._agent_service.resume_agent(command.agent_id)
            return AgentStateSuccess(message="Agent resumed successfully", state=state)

        return AgentStateFailure(error=f"Unknown action: {command.action}")


class DeleteAgentUseCase(CommandHandler[DeleteAgentCommand]):
    """Delete an agent — validates ownership → removes via service port."""

    def __init__(self, *, agent_service: AgentServicePort) -> None:
        self._agent_service = agent_service

    def handle(self, command: DeleteAgentCommand) -> Any:
        return self.execute(command)

    def execute(self, command: DeleteAgentCommand) -> DeleteAgentResult:
        agent = self._agent_service.get_agent(command.agent_id)
        if agent is None:
            return DeleteAgentFailure(error="Agent not found", status_code=404)

        if getattr(agent, "user_id", None) != command.user_id:
            return DeleteAgentFailure(error="Permission denied", status_code=403)

        try:
            success = self._agent_service.remove_agent(command.agent_id)
        except Exception as exc:
            return DeleteAgentFailure(error=f"Failed to delete agent: {str(exc)}", status_code=500)

        if not success:
            return DeleteAgentFailure(error="Failed to delete agent", status_code=500)

        return DeleteAgentSuccess()

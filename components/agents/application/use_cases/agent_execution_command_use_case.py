"""Use case for agent execution commands.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_execution_command_port import (
    AgentExecutionCommandPort,
    ExecuteAgentCommand,
    ExecuteAgentResult,
)
from components.shared_kernel.application.handlers import CommandHandler


class ExecuteAgentUseCase(CommandHandler[ExecuteAgentCommand]):
    def __init__(self, port: AgentExecutionCommandPort) -> None:
        self._port = port

    def handle(self, command: ExecuteAgentCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: ExecuteAgentCommand) -> ExecuteAgentResult:
        return self._port.execute_agent(command=command)

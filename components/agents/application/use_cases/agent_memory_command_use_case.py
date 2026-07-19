"""Use cases: Agent memory write commands.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_memory_command_port import (
    AddSystemMessageCommand,
    AddSystemMessageResult,
    AgentMemoryCommandPort,
    ClearMemoryCommand,
    ClearMemoryResult,
)
from components.shared_kernel.application.handlers import CommandHandler


class ClearAgentMemoryUseCase(CommandHandler[ClearMemoryCommand]):
    def __init__(self, port: AgentMemoryCommandPort) -> None:
        self._port = port

    def handle(self, command: ClearMemoryCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: ClearMemoryCommand) -> ClearMemoryResult:
        return self._port.clear_memory(command=command)


class AddAgentSystemMessageUseCase(CommandHandler[AddSystemMessageCommand]):
    def __init__(self, port: AgentMemoryCommandPort) -> None:
        self._port = port

    def handle(self, command: AddSystemMessageCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command=command)

    def execute(self, *, command: AddSystemMessageCommand) -> AddSystemMessageResult:
        return self._port.add_system_message(command=command)

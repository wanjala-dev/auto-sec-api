"""Port: Agent memory write commands.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClearMemoryCommand:
    agent_id: str
    user_id: str


@dataclass
class ClearMemoryResult:
    agent_id: str = ""
    message: str = ""


@dataclass(frozen=True)
class AddSystemMessageCommand:
    agent_id: str
    user_id: str
    content: str = ""


@dataclass
class AddSystemMessageResult:
    agent_id: str = ""
    content: str = ""
    message: str = ""


class AgentMemoryCommandPort(abc.ABC):
    """Secondary port for agent memory write operations."""

    @abc.abstractmethod
    def clear_memory(self, *, command: ClearMemoryCommand) -> ClearMemoryResult:
        """Clear agent memory and conversation history.

        Raises LookupError if agent not found.
        Raises PermissionError if user does not own the agent.
        """
        ...

    @abc.abstractmethod
    def add_system_message(self, *, command: AddSystemMessageCommand) -> AddSystemMessageResult:
        """Add a system message to agent memory.

        Raises LookupError if agent not found.
        Raises PermissionError if user does not own the agent.
        Raises ValueError if content is empty.
        """
        ...

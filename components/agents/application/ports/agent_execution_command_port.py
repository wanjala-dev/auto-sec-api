"""Port: Agent execution command operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecuteAgentCommand:
    agent_id: str
    query: str
    user_id: str


@dataclass
class ExecuteAgentResult:
    agent_id: str = ""
    execution_id: str = ""
    task_id: str = ""
    status: str = ""
    progress: Any = None
    state: Any = None
    conversation_id: str | None = None


class AgentExecutionCommandPort(abc.ABC):
    """Secondary port for agent execution write operations."""

    @abc.abstractmethod
    def execute_agent(self, *, command: ExecuteAgentCommand) -> ExecuteAgentResult:
        """Execute a query against an agent.

        Raises AgentNotFoundError if agent does not exist.
        Raises AgentDisabledError if agent profile is disabled.
        Raises AgentPermissionError if user lacks execute permission.
        """
        ...

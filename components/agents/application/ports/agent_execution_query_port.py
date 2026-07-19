"""Port: Agent execution read queries.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionDetailRequest:
    """Parameters for a single execution detail query."""

    execution_id: Any
    limit: int | None = None
    offset: int = 0
    order: str = "asc"


@dataclass(frozen=True)
class ExecutionListRequest:
    """Parameters for paginated execution list query."""

    agent_id: str
    limit: int | None = 50
    offset: int = 0
    order: str = "desc"
    include_state: bool = False


@dataclass
class ConversationPagination:
    """Pagination metadata for conversation messages."""

    limit: int | None = None
    offset: int = 0
    order: str = "asc"
    total: int = 0
    returned: int = 0
    has_more: bool = False
    next_offset: int | None = None


@dataclass
class ExecutionDetailData:
    """Full execution detail with optional conversation history."""

    execution_id: Any = None
    agent_id: str = ""
    agent_record: Any = None
    task_id: Any = None
    status: str = ""
    success: bool | None = None
    progress: int | None = None
    state: Any = None
    result: Any = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    conversation_id: str | None = None
    conversation_messages: list[Any] = field(default_factory=list)
    conversation_pagination: ConversationPagination = field(default_factory=ConversationPagination)


@dataclass
class ExecutionListData:
    """Paginated list of executions for an agent."""

    agent_id: str = ""
    agent_record: Any = None
    executions: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    has_more: bool = False
    returned: int = 0
    next_offset: int | None = None


@dataclass(frozen=True)
class AgentMemoryRequest:
    """Parameters for agent memory query."""

    agent_id: str
    limit: int | None = None
    offset: int = 0
    order: str = "asc"


@dataclass
class AgentMemoryData:
    """Agent memory with stats, conversation history, and last execution."""

    agent_id: str = ""
    agent_record: Any = None
    memory_stats: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[Any] = field(default_factory=list)
    last_execution: dict[str, Any] | None = None
    last_progress: int | None = None
    pagination: ConversationPagination = field(default_factory=ConversationPagination)


class AgentExecutionQueryPort(abc.ABC):
    """Secondary port for agent execution read queries."""

    @abc.abstractmethod
    def fetch_execution_detail(self, *, request: ExecutionDetailRequest) -> ExecutionDetailData:
        """Fetch a single execution with conversation history.

        Raises LookupError if execution not found.
        """
        ...

    @abc.abstractmethod
    def fetch_execution_list(self, *, request: ExecutionListRequest) -> ExecutionListData:
        """Fetch paginated executions for an agent.

        Raises LookupError if agent not found.
        """
        ...

    @abc.abstractmethod
    def fetch_agent_memory(self, *, request: AgentMemoryRequest) -> AgentMemoryData:
        """Fetch agent memory stats, conversation history, and latest execution.

        Raises LookupError if agent not found.
        """
        ...

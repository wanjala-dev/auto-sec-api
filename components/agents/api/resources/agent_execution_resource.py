"""Response DTO for agent execution endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionLogEntryResource:
    """A single execution log entry."""
    timestamp: str
    level: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentExecutionResource:
    """Output DTO for agent execution detail endpoints."""
    execution_id: int
    agent_id: str
    task_id: str | None = None
    status: str = "pending"
    progress: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentExecutionCollectionResource:
    """Output DTO for agent execution list endpoints."""
    executions: list[AgentExecutionResource] = field(default_factory=list)
    total: int = 0
    count: int = 0
    pagination: dict[str, Any] = field(default_factory=dict)

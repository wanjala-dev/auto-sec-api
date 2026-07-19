"""Response DTO for agent memory endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryEntryResource:
    """A single memory entry in conversation history."""
    timestamp: str
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaginationResource:
    """Pagination metadata for list endpoints."""
    limit: int | None = None
    offset: int = 0
    total: int = 0
    next_offset: int | None = None


@dataclass(frozen=True)
class AgentMemoryResource:
    """Output DTO for agent memory detail endpoints."""
    agent_id: str
    memory_stats: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[MemoryEntryResource] = field(default_factory=list)
    last_execution: str | None = None
    last_progress: int = 0
    pagination: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClearMemoryResource:
    """Output DTO for clear memory endpoint."""
    agent_id: str
    message: str


@dataclass(frozen=True)
class AddSystemMessageResource:
    """Output DTO for add system message endpoint."""
    agent_id: str
    content: str
    message: str = "System message added successfully"

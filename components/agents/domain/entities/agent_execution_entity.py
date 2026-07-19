"""Pure domain entity for agent execution records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AgentExecutionEntity:
    id: int
    agent_id: UUID
    query: str
    status: str
    success: bool = True
    result: str = ""
    error_message: str = ""
    execution_time_ms: int | None = None
    task_id: str = ""
    progress: int = 0
    state: dict = field(default_factory=dict)
    triggered_by_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

"""Pure domain entity for an AI Agent — no ORM dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AgentEntity:
    agent_id: UUID
    agent_type: str
    user_id: UUID
    status: str
    config: dict = field(default_factory=dict)
    workspace_id: UUID | None = None
    department_id: UUID | None = None
    last_query: str = ""
    last_result: str = ""
    execution_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_executed: datetime | None = None


@dataclass(frozen=True)
class AgentProfileEntity:
    agent_id: UUID
    display_name: str
    summary: str
    avatar_url: str
    tags: list[str] = field(default_factory=list)
    visibility: str = "workspace_only"
    allow_followers: bool = True
    allow_ratings: bool = True
    allow_comments: bool = True
    is_disabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

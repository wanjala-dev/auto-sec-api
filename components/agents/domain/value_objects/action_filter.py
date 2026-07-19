"""Filter value object for AI action queries (CQRS read side)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ActionFilter:
    workspace_id: UUID | None = None
    status: str | None = None
    agent_type: str | None = None
    action_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    search_query: str | None = None
    limit: int = 50
    offset: int = 0

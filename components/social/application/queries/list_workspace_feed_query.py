"""Query DTO for the workspace feed endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ListWorkspaceFeedQuery:
    viewer_id: UUID
    workspace_id: UUID
    team_id: int | None = None
    cursor: str | None = None
    limit: int = 20

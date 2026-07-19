"""Output DTOs for column endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnResource:
    """Output DTO for column detail endpoints (GET /api/projects/columns/<column_id>/)."""
    id: int | None = None
    title: str | None = None
    project: int | None = None
    team: int | None = None
    workspace: str | None = None
    created_by: str | int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    order: int | None = None
    is_deleted: bool | None = None
    tasks: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ColumnCollectionResource:
    """Output DTO for column list endpoints (GET /api/projects/columns/)."""
    items: list[ColumnResource]
    count: int = 0

"""Input DTO for column updates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateColumnRequest:
    """Input DTO for PUT /api/projects/columns/<column_id>/ endpoint (ColumnsView.put).

    Used to update column properties including soft delete.
    """
    column_id: str | int
    title: str | None = None
    is_deleted: bool | None = None
    order: int | None = None

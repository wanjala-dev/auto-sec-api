"""Command DTOs: persisted saved board views (task #74, on the ADR 0030 substrate).

Frozen dataclasses only — no Django imports. ``None`` means "not provided"
on the partial update (a name can never be nulled; clearing the filter is an
explicit ``{}``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateBoardViewCommand:
    """A user saves the lens they are looking through as a personal view."""

    team_id: Any
    name: str
    filter: dict = field(default_factory=dict)
    group_by: str = "status"


@dataclass(frozen=True)
class UpdateBoardViewCommand:
    """Rename / re-filter / reorder an existing personal view (partial)."""

    view_id: Any
    name: str | None = None
    filter: dict | None = None
    group_by: str | None = None
    order: int | None = None

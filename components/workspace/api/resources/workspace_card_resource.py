"""Resource DTO for workspace card entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceCardResource:
    """Output DTO for workspace card detail endpoints.

    Represents a single workspace card for visual representation.
    """
    id: int | None = None
    workspace: str | None = None
    name: str | None = None
    checked: bool = False
    text: str | None = None
    photo_url: str | None = None


@dataclass(frozen=True)
class WorkspaceCardCollectionResource:
    """Output DTO for workspace card list endpoints.

    Represents a collection of workspace cards.
    """
    items: list[WorkspaceCardResource] | None = None
    count: int = 0

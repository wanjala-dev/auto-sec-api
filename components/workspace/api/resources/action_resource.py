"""Resource DTO for action entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionResource:
    """Output DTO for action detail endpoints.

    Represents a single action item within a workspace.
    """
    id: int | None = None
    title: str | None = None
    workspace: str | None = None
    owner: str | None = None
    privacy: str | None = None
    url: str | None = None
    created_date: str | None = None
    likes: list[dict] | None = None
    dislikes: list[dict] | None = None


@dataclass(frozen=True)
class ActionCollectionResource:
    """Output DTO for action list endpoints.

    Represents a collection of actions.
    """
    items: list[ActionResource] | None = None
    count: int = 0

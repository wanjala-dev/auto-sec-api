"""Resource DTO for tag entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagResource:
    """Output DTO for tag endpoints.

    Represents a tag that can be applied to workspaces and comments.
    """
    id: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class TagCollectionResource:
    """Output DTO for tag list endpoints.

    Represents a collection of tags.
    """
    items: list[TagResource] | None = None
    count: int = 0

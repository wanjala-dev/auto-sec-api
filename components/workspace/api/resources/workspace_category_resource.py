"""Resource DTO for workspace category entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubCategoryResource:
    """Output DTO for subcategory details."""
    id: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class WorkspaceCategoryResource:
    """Output DTO for workspace category detail endpoints.

    Represents a workspace category with its subcategories.
    """
    id: int | None = None
    name: str | None = None
    subcategories: list[SubCategoryResource] | None = None


@dataclass(frozen=True)
class WorkspaceCategoryCollectionResource:
    """Output DTO for workspace category list endpoints.

    Represents a collection of workspace categories.
    """
    items: list[WorkspaceCategoryResource] | None = None
    count: int = 0

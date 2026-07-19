"""Resource DTOs for category endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryResource:
    """Output DTO for category detail endpoints."""
    id: int
    name: str
    news_count: int = 0


@dataclass(frozen=True)
class CategoryCollectionResource:
    """Output DTO for category list endpoint."""
    items: list[CategoryResource]
    count: int = 0

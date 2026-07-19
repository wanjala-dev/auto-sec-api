"""Resource DTOs for tag endpoints.

Output data classes for GET /social/tag endpoints and responses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagResource:
    """Output DTO for tag detail endpoints."""
    id: str
    name: str


@dataclass(frozen=True)
class TagCollectionResource:
    """Output DTO for tag list endpoints."""
    items: list[TagResource]
    count: int = 0

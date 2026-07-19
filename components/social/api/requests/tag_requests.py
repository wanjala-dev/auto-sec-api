"""Request DTOs for tag endpoints.

Input data classes for POST /social/tag and related endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateTagRequest:
    """Input DTO for POST /social/tag endpoint."""
    name: str


@dataclass(frozen=True)
class UpdateTagRequest:
    """Input DTO for PUT/PATCH /social/tag/<id>/ endpoint."""
    name: str | None = None

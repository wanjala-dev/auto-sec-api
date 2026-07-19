"""Request DTOs for post endpoints.

Input data classes for POST /social/ and related endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreatePostRequest:
    """Input DTO for POST /social/ endpoint."""
    body: str
    shared_body: str | None = None
    author: str | None = None
    shared_user: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class UpdatePostRequest:
    """Input DTO for PUT/PATCH /social/<id>/ endpoint."""
    body: str | None = None
    shared_body: str | None = None
    shared_user: str | None = None
    tags: list[str] | None = None

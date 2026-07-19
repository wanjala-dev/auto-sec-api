"""Resource DTOs for follower endpoints.

Output data classes for GET/POST follower endpoints and responses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FollowerActionResource:
    """Output DTO for POST follow/unfollow endpoints."""
    success: bool
    message: str


@dataclass(frozen=True)
class FollowerResource:
    """Output DTO for follower data."""
    id: str
    username: str
    email: str | None = None


@dataclass(frozen=True)
class FollowerCollectionResource:
    """Output DTO for follower list endpoints."""
    items: list[FollowerResource]
    count: int = 0

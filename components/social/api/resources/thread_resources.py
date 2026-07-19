"""Resource DTOs for thread/conversation endpoints.

Output data classes for GET /social/thread endpoints and responses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadResource:
    """Output DTO for thread detail endpoints."""
    id: str
    user: str
    receiver: str
    created_at: str | None = None
    workspace: str | None = None
    thread_type: str | None = None
    is_archived: bool = False
    is_starred: bool = False
    archived_at: str | None = None
    starred_at: str | None = None


@dataclass(frozen=True)
class ThreadCollectionResource:
    """Output DTO for thread list endpoints."""
    items: list[ThreadResource]
    count: int = 0


@dataclass(frozen=True)
class ThreadActionResource:
    """Output DTO for thread action endpoints (archive/star)."""
    message: str
    thread_id: str
    is_archived: bool | None = None
    is_starred: bool | None = None
    archived_at: str | None = None
    starred_at: str | None = None

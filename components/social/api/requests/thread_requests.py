"""Request DTOs for thread/conversation endpoints.

Input data classes for POST /social/thread and related endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateThreadRequest:
    """Input DTO for POST /social/thread endpoint."""
    username: str
    workspace_id: str | None = None


@dataclass(frozen=True)
class ThreadArchiveRequest:
    """Input DTO for POST /social/thread/<id>/archive endpoint."""
    pass


@dataclass(frozen=True)
class ThreadUnarchiveRequest:
    """Input DTO for POST /social/thread/<id>/unarchive endpoint."""
    pass


@dataclass(frozen=True)
class ThreadStarRequest:
    """Input DTO for POST /social/thread/<id>/star endpoint."""
    pass


@dataclass(frozen=True)
class ThreadUnstarRequest:
    """Input DTO for POST /social/thread/<id>/unstar endpoint."""
    pass

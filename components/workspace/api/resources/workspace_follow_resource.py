"""Resource DTO for workspace follow endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceFollowResource:
    """Output DTO for workspace follow/unfollow endpoints.

    Represents the result of follow/unfollow operations.
    """
    status: str | None = None
    followed: list[str] | None = None
    unfollowed: list[str] | None = None

"""Request DTOs for follower endpoints.

Input data classes for POST /social/followers endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AddFollowerRequest:
    """Input DTO for POST /social/users/<user_id>/follow endpoint."""
    pass


@dataclass(frozen=True)
class RemoveFollowerRequest:
    """Input DTO for POST /social/users/<user_id>/unfollow endpoint."""
    pass

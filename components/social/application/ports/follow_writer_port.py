"""Port for mutating the follow graph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class FollowWriterPort(ABC):
    @abstractmethod
    def add_follow(self, *, follower_id: UUID, followee_id: UUID) -> None:
        """Make ``follower_id`` follow ``followee_id``. Idempotent."""

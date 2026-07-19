"""Port for reading the follow graph."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import FrozenSet
from uuid import UUID


class FollowReaderPort(ABC):
    @abstractmethod
    def list_followed_user_ids(self, user_id: UUID) -> FrozenSet[UUID]:
        """Return the IDs of users that ``user_id`` follows."""

    @abstractmethod
    def is_following(self, *, user_id: UUID, target_id: UUID) -> bool:
        ...

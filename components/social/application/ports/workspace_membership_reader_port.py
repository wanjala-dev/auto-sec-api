"""Port for reading workspace and team membership."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import FrozenSet
from uuid import UUID


class WorkspaceMembershipReaderPort(ABC):
    @abstractmethod
    def list_workspace_member_ids(self, workspace_id: UUID) -> FrozenSet[UUID]:
        ...

    @abstractmethod
    def is_workspace_owner(self, *, user_id: UUID, workspace_id: UUID) -> bool:
        ...

    @abstractmethod
    def list_user_team_ids(self, *, user_id: UUID, workspace_id: UUID) -> FrozenSet[int]:
        ...

    @abstractmethod
    def is_team_member(self, *, user_id: UUID, team_id: int) -> bool:
        ...

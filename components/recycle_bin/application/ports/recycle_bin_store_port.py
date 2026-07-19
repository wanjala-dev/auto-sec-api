from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage


class RecycleBinStorePort(ABC):

    @abstractmethod
    def save(self, entry: RecycleBinEntry) -> None: ...

    @abstractmethod
    def find_by_id(self, entry_id: UUID) -> RecycleBinEntry | None: ...

    @abstractmethod
    def find_by_entity(self, entity_type: str, entity_id: str) -> RecycleBinEntry | None: ...

    @abstractmethod
    def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        stage: DeletionStage | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RecycleBinEntry]: ...

    @abstractmethod
    def count_for_workspace(self, workspace_id: UUID, *, stage: DeletionStage | None = None) -> int: ...

    @abstractmethod
    def delete(self, entry_id: UUID) -> None: ...

    @abstractmethod
    def find_expired_trashed(self, now: datetime) -> list[RecycleBinEntry]: ...

    @abstractmethod
    def find_expired_tombstoned(self, now: datetime) -> list[RecycleBinEntry]: ...

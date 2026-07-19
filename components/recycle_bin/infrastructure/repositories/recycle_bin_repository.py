from __future__ import annotations

from datetime import datetime
from uuid import UUID

from components.recycle_bin.application.ports.recycle_bin_store_port import RecycleBinStorePort
from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry as RecycleBinEntryEntity
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.mappers.db.recycle_bin_mapper import to_domain, to_orm_kwargs


class DjangoRecycleBinRepository(RecycleBinStorePort):

    def save(self, entry: RecycleBinEntryEntity) -> None:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        kwargs = to_orm_kwargs(entry)
        entry_id = kwargs.pop("id")
        RecycleBinEntry.objects.update_or_create(id=entry_id, defaults=kwargs)

    def find_by_id(self, entry_id: UUID) -> RecycleBinEntryEntity | None:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        try:
            obj = RecycleBinEntry.objects.get(id=entry_id)
        except RecycleBinEntry.DoesNotExist:
            return None
        return to_domain(obj)

    def find_by_entity(self, entity_type: str, entity_id: str) -> RecycleBinEntryEntity | None:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        obj = RecycleBinEntry.objects.filter(entity_type=entity_type, entity_id=entity_id).first()
        if obj is None:
            return None
        return to_domain(obj)

    def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        stage: DeletionStage | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RecycleBinEntryEntity]:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        qs = RecycleBinEntry.objects.filter(workspace_id=workspace_id).order_by("-deleted_at")
        if stage is not None:
            qs = qs.filter(stage=stage.value)
        if entity_type is not None:
            qs = qs.filter(entity_type=entity_type)
        return [to_domain(obj) for obj in qs[offset : offset + limit]]

    def count_for_workspace(self, workspace_id: UUID, *, stage: DeletionStage | None = None) -> int:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        qs = RecycleBinEntry.objects.filter(workspace_id=workspace_id)
        if stage is not None:
            qs = qs.filter(stage=stage.value)
        return qs.count()

    def delete(self, entry_id: UUID) -> None:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        RecycleBinEntry.objects.filter(id=entry_id).delete()

    def find_expired_trashed(self, now: datetime) -> list[RecycleBinEntryEntity]:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        qs = RecycleBinEntry.objects.filter(
            stage=DeletionStage.TRASHED.value,
            trashed_until__lte=now,
        )
        return [to_domain(obj) for obj in qs]

    def find_expired_tombstoned(self, now: datetime) -> list[RecycleBinEntryEntity]:
        from infrastructure.persistence.recycle_bin.models import RecycleBinEntry

        qs = RecycleBinEntry.objects.filter(
            stage=DeletionStage.TOMBSTONED.value,
            tombstoned_until__lte=now,
        )
        return [to_domain(obj) for obj in qs]

from __future__ import annotations

from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry as RecycleBinEntryEntity
from components.recycle_bin.domain.enums import DeletionStage


def to_domain(orm_obj) -> RecycleBinEntryEntity:
    """Map an ORM RecycleBinEntry instance to the frozen domain dataclass."""
    return RecycleBinEntryEntity(
        id=orm_obj.id,
        workspace_id=orm_obj.workspace_id,
        entity_type=orm_obj.entity_type,
        # ORM column is CharField now; cast defensively for any rows
        # written before the migration that may still surface as UUID.
        entity_id=str(orm_obj.entity_id),
        entity_name=orm_obj.entity_name,
        stage=DeletionStage(orm_obj.stage),
        deleted_by=orm_obj.deleted_by_id,
        deleted_at=orm_obj.deleted_at,
        trashed_until=orm_obj.trashed_until,
        tombstoned_at=orm_obj.tombstoned_at,
        tombstoned_by=orm_obj.tombstoned_by_id,
        tombstoned_until=orm_obj.tombstoned_until,
        snapshot=orm_obj.snapshot or {},
        cascade_snapshot=orm_obj.cascade_snapshot or {},
        restored_at=orm_obj.restored_at,
        restored_by=orm_obj.restored_by_id,
    )


def to_orm_kwargs(entity: RecycleBinEntryEntity) -> dict:
    """Map a frozen domain dataclass to a dict suitable for ORM create/update."""
    return {
        "id": entity.id,
        "workspace_id": entity.workspace_id,
        "entity_type": entity.entity_type,
        "entity_id": entity.entity_id,
        "entity_name": entity.entity_name,
        "stage": entity.stage.value,
        "deleted_by_id": entity.deleted_by,
        "deleted_at": entity.deleted_at,
        "trashed_until": entity.trashed_until,
        "tombstoned_at": entity.tombstoned_at,
        "tombstoned_by_id": entity.tombstoned_by,
        "tombstoned_until": entity.tombstoned_until,
        "snapshot": entity.snapshot,
        "cascade_snapshot": entity.cascade_snapshot,
        "restored_at": entity.restored_at,
        "restored_by_id": entity.restored_by,
    }

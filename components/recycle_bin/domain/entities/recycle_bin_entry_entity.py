from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.recycle_bin.domain.enums import DeletionStage


@dataclass(frozen=True)
class RecycleBinEntry:
    id: UUID
    workspace_id: UUID
    entity_type: str
    # Stored as a string so the bin can hold entries for both UUID and
    # integer PKs. Producers cast whatever PK they hold to ``str`` and
    # repository persistence keeps the round-trip stable.
    entity_id: str
    entity_name: str
    stage: DeletionStage
    deleted_by: UUID | None
    deleted_at: datetime
    trashed_until: datetime
    tombstoned_at: datetime | None
    tombstoned_by: UUID | None
    tombstoned_until: datetime | None
    snapshot: dict
    cascade_snapshot: dict
    restored_at: datetime | None
    restored_by: UUID | None

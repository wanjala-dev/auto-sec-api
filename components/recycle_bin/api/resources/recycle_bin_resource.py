from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class RecycleBinEntryResource:
    id: UUID
    entity_type: str
    # str (not UUID) so the resource can carry entity_ids for integer-
    # PK entities as well as UUIDs.
    entity_id: str
    entity_name: str
    stage: str
    deleted_by: UUID | None
    deleted_at: datetime
    trashed_until: datetime
    tombstoned_at: datetime | None = None
    snapshot: dict = field(default_factory=dict)

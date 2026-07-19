from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TrashEntityRequest:
    workspace_id: UUID
    entity_type: str
    entity_id: UUID
    deleted_by: UUID

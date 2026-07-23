"""Provenance event — an action edge (Actor → Resource). The *actual*."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from components.provenance.domain.value_objects.enums import SourceSystem


@dataclass(frozen=True)
class ProvenanceEventEntity:
    id: UUID
    workspace_id: UUID
    actor_id: UUID
    resource_id: UUID
    action: str
    occurred_at: datetime
    source_system: SourceSystem
    origin: str
    origin_id: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action:
            raise ValueError("ProvenanceEventEntity.action is required")
        if not self.origin_id:
            raise ValueError("ProvenanceEventEntity.origin_id is required")
        # Freeze the metadata mapping so the entity stays immutable.
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

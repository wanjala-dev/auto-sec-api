"""Resource node — a thing acted upon (system, store, repo, channel, bucket)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.provenance.domain.value_objects.enums import SourceSystem


@dataclass(frozen=True)
class ResourceEntity:
    id: UUID
    workspace_id: UUID
    resource_type: str
    source_system: SourceSystem
    external_ref: str
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("ResourceEntity.resource_type is required")
        if not self.external_ref:
            raise ValueError("ResourceEntity.external_ref is required")

"""Actor node — a human, service account, AI agent, or vendor integration."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.provenance.domain.value_objects.enums import ActorType, SourceSystem


@dataclass(frozen=True)
class ActorEntity:
    id: UUID
    workspace_id: UUID
    actor_type: ActorType
    source_system: SourceSystem
    external_ref: str
    display_name: str = ""
    user_id: UUID | None = None
    agent_ref: UUID | None = None
    integration_ref: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.external_ref:
            raise ValueError("ActorEntity.external_ref is required")

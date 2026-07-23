"""Immutable domain entities for the provenance/access graph.

Frozen dataclasses — no ORM, no Django. Business invariants validated in
``__post_init__``. Mapped from the ORM models by ``mappers/db``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from components.provenance.domain.value_objects.enums import (
    ActorType,
    PermissionLevel,
    SourceSystem,
)


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


@dataclass(frozen=True)
class GrantEntity:
    """A permission edge — the *potential*."""

    id: UUID
    workspace_id: UUID
    actor_id: UUID
    resource_id: UUID
    permissions: tuple[PermissionLevel, ...] = ()
    scope: str = ""
    source: str = ""
    is_active: bool = True

    @property
    def is_admin(self) -> bool:
        return PermissionLevel.ADMIN in self.permissions


@dataclass(frozen=True)
class ProvenanceEventEntity:
    """An action edge — the *actual*. Append-only."""

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

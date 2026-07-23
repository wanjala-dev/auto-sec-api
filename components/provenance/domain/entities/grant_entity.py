"""Grant — a permission edge (Actor → Resource). The *potential*."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.provenance.domain.value_objects.enums import PermissionLevel


@dataclass(frozen=True)
class GrantEntity:
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

"""ORM adapter for :class:`WorkspaceRoleReaderPort`."""

from __future__ import annotations

from uuid import UUID

from django.db.models import Q

from components.membership.application.ports.workspace_role_reader_port import (
    WorkspaceRoleReaderPort,
)
from components.membership.domain.entities.workspace_role_entity import (
    WorkspaceRoleEntity,
)


def _to_entity(model) -> WorkspaceRoleEntity:
    """Map an ORM ``WorkspaceRole`` row to its domain entity."""
    return WorkspaceRoleEntity(
        id=model.id,
        slug=model.slug,
        name=model.name,
        description=model.description or "",
        permissions=frozenset(model.permissions or []),
        is_system=bool(model.is_system),
        workspace_id=model.workspace_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class OrmWorkspaceRoleRepository(WorkspaceRoleReaderPort):
    """Reads ``WorkspaceRole`` rows from Postgres."""

    def get_by_slug(
        self,
        slug: str,
        workspace_id: UUID | None = None,
    ) -> WorkspaceRoleEntity | None:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        if workspace_id is not None:
            custom = (
                WorkspaceRole.objects
                .filter(workspace_id=workspace_id, slug=slug, is_system=False)
                .first()
            )
            if custom is not None:
                return _to_entity(custom)

        system = (
            WorkspaceRole.objects
            .filter(workspace__isnull=True, slug=slug, is_system=True)
            .first()
        )
        return _to_entity(system) if system is not None else None

    def get_by_id(self, role_id: UUID) -> WorkspaceRoleEntity | None:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        model = WorkspaceRole.objects.filter(id=role_id).first()
        return _to_entity(model) if model is not None else None

    def list_system_roles(self) -> list[WorkspaceRoleEntity]:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        models = WorkspaceRole.objects.filter(
            workspace__isnull=True, is_system=True
        ).order_by("name")
        return [_to_entity(m) for m in models]

    def list_available_for_workspace(
        self, workspace_id: UUID
    ) -> list[WorkspaceRoleEntity]:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        models = (
            WorkspaceRole.objects
            .filter(
                Q(workspace__isnull=True, is_system=True)
                | Q(workspace_id=workspace_id, is_system=False)
            )
            .order_by("is_system", "name")
        )
        return [_to_entity(m) for m in models]

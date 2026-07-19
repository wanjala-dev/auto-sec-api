"""Read port for workspace roles.

Phase 1a reader-only: list/lookup system + workspace-scoped roles. Write
operations (create custom role, edit permissions, delete) land in a
later phase once the frontend editor is ready.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.membership.domain.entities.workspace_role_entity import (
    WorkspaceRoleEntity,
)


class WorkspaceRoleReaderPort(ABC):
    """Port for reading ``WorkspaceRole`` rows as domain entities."""

    @abstractmethod
    def get_by_slug(
        self,
        slug: str,
        workspace_id: UUID | None = None,
    ) -> WorkspaceRoleEntity | None:
        """Return the role matching ``slug`` scoped to ``workspace_id``.

        Lookup order:
        1. Workspace-scoped custom role with the given slug (if ``workspace_id`` supplied).
        2. System role with the given slug (``workspace_id=None``, ``is_system=True``).
        3. ``None`` if nothing matches.
        """

    @abstractmethod
    def get_by_id(self, role_id: UUID) -> WorkspaceRoleEntity | None:
        """Return a role by primary key, or ``None`` if it doesn't exist."""

    @abstractmethod
    def list_system_roles(self) -> list[WorkspaceRoleEntity]:
        """Return every system role (``is_system=True``, ``workspace=None``)."""

    @abstractmethod
    def list_available_for_workspace(
        self, workspace_id: UUID
    ) -> list[WorkspaceRoleEntity]:
        """Return system roles plus the workspace's own custom roles.

        The union an admin sees when assigning a role to a member.
        """

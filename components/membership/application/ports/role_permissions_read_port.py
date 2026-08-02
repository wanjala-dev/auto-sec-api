"""Port: read the workspace RBAC facts the permission resolver needs.

``membership_has_permission`` (``application/services/membership_permission_service.py``)
resolves "does this membership carry permission X?" from three grant sources it
does NOT own — they live on the ``workspaces`` persistence app (``WorkspaceRole``,
``WorkspacePermissionGrant``, ``WorkspaceGroupMembership``). Reading those tables
from the membership *application* layer violated architecture-manifesto Rule 2
(dependencies point inward — the application layer must reach persistence through
a port, not the ORM) and the architecture skill's C3 (a context reads another's
facts through its own read-port, not by importing the shared persistence models).

This port is that read seam. It is shaped to the resolver's needs (Herberto Graça:
ports fit the Application Core, not the tool API), returning frozen-dataclass DTOs
/ primitives — never ORM instances across the boundary — and is always
workspace-scoped so a grant in another workspace can never leak.

Two reads, matching exactly what the resolver does today:

1. ``get_system_role_permissions(slug)`` — the legacy-``role``-string fallback:
   look up the seeded system role (``workspace=None, is_system=True``) by slug and
   return its permission keys. Returns ``None`` when no such system role exists
   (the resolver logs + denies).
2. ``has_grant(workspace_id, user_id, permission_key)`` — the direct-user +
   group-mediated ``WorkspacePermissionGrant`` escape hatch, resolved as one
   workspace-scoped boolean (a direct grant on the user, or a grant on any group
   the user belongs to in that workspace).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class SystemRolePermissions:
    """The permission keys carried by a seeded system role."""

    slug: str
    permission_keys: frozenset[str]


class RolePermissionsReadPort(ABC):
    """Read workspace RBAC grant facts for the permission resolver."""

    @abstractmethod
    def get_system_role_permissions(self, slug: str) -> SystemRolePermissions | None:
        """Return the seeded system role's permissions for ``slug``.

        System roles are ``workspace=None, is_system=True``. Returns ``None`` when
        no system role matches the slug (an unresolved legacy role — the resolver
        denies and logs).
        """

    @abstractmethod
    def has_grant(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        permission_key: str,
    ) -> bool:
        """Return ``True`` if a ``WorkspacePermissionGrant`` covers the key.

        Workspace-scoped: matches a direct grant on the user, or a grant on any
        ``WorkspaceGroup`` the user belongs to *in this workspace*. A grant in a
        different workspace never leaks (tenant isolation).
        """

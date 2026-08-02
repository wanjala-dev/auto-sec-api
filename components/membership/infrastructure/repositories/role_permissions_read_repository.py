"""Adapter: read workspace RBAC grant facts from the ``workspaces`` app.

Implements :class:`RolePermissionsReadPort`. This is the same sanctioned
cross-context read pattern the ``remediation`` context uses
(``FindingRemediationFactsPort`` → ``BoardFindingFactsRepository`` reading
``project.Task``): the membership context defines its own read-port shaped to the
resolver's need, and this infrastructure adapter reads the shared ``workspaces``
persistence models. Reading ``infrastructure.persistence.workspaces.models`` is a
persistence read from an infrastructure adapter — the sanctioned place for ORM
access — NOT an application-layer ORM import.

The two reads mirror exactly what ``membership_has_permission`` did inline before
the extraction, preserving behaviour (system-role fallback + direct/group grant
short-circuit) query-for-query.
"""

from __future__ import annotations

from uuid import UUID

from components.membership.application.ports.role_permissions_read_port import (
    RolePermissionsReadPort,
    SystemRolePermissions,
)


class OrmRolePermissionsReadRepository(RolePermissionsReadPort):
    """Reads ``WorkspaceRole`` / ``WorkspacePermissionGrant`` /
    ``WorkspaceGroupMembership`` rows from Postgres."""

    def get_system_role_permissions(self, slug: str) -> SystemRolePermissions | None:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        system_role = (
            WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=slug).only("permissions").first()
        )
        if system_role is None:
            return None
        return SystemRolePermissions(
            slug=slug,
            permission_keys=frozenset(system_role.permissions or []),
        )

    def has_grant(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        permission_key: str,
    ) -> bool:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroupMembership,
            WorkspacePermissionGrant,
        )

        if WorkspacePermissionGrant.objects.filter(
            workspace_id=workspace_id,
            user_id=user_id,
            permission_key=permission_key,
        ).exists():
            return True

        user_group_ids = list(
            WorkspaceGroupMembership.objects.filter(
                user_id=user_id,
                group__workspace_id=workspace_id,
            ).values_list("group_id", flat=True)
        )
        if not user_group_ids:
            return False

        return WorkspacePermissionGrant.objects.filter(
            workspace_id=workspace_id,
            group_id__in=user_group_ids,
            permission_key=permission_key,
        ).exists()

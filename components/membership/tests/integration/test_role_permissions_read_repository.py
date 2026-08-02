"""Integration tests for :class:`OrmRolePermissionsReadRepository`.

Proves the RBAC read-port adapter resolves the same three grant sources the
``membership_has_permission`` resolver relied on when it read the ORM inline —
system-role permissions (legacy fallback), direct-user grants, and
group-mediated grants — and that every read is workspace-scoped (no
cross-workspace leak).
"""

from __future__ import annotations

import pytest

from components.membership.infrastructure.repositories.role_permissions_read_repository import (
    OrmRolePermissionsReadRepository,
)


@pytest.fixture
def reader() -> OrmRolePermissionsReadRepository:
    return OrmRolePermissionsReadRepository()


@pytest.mark.django_db
class TestSystemRolePermissions:
    def test_returns_permission_keys_for_seeded_system_role(self, reader) -> None:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        WorkspaceRole.objects.update_or_create(
            workspace=None,
            slug="admin",
            defaults={
                "name": "Admin",
                "permissions": ["manage_settings", "manage_budgets", "view_budgets"],
                "is_system": True,
            },
        )

        result = reader.get_system_role_permissions("admin")

        assert result is not None
        assert result.slug == "admin"
        assert result.permission_keys == frozenset({"manage_settings", "manage_budgets", "view_budgets"})

    def test_returns_none_for_unknown_slug(self, reader) -> None:
        assert reader.get_system_role_permissions("nonsense") is None

    def test_ignores_workspace_scoped_role_with_same_slug(self, reader, workspace_factory) -> None:
        """Only system roles (workspace=None, is_system=True) resolve here."""
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        workspace = workspace_factory()
        WorkspaceRole.objects.create(
            workspace=workspace,
            slug="custom_ops",
            name="Custom Ops",
            permissions=["manage_budgets"],
            is_system=False,
        )

        assert reader.get_system_role_permissions("custom_ops") is None


@pytest.mark.django_db
class TestDirectUserGrants:
    def test_direct_grant_resolves(self, reader, workspace_factory, user_factory) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePermissionGrant,
        )

        workspace = workspace_factory()
        user = user_factory()
        WorkspacePermissionGrant.objects.create(
            workspace=workspace,
            user=user,
            permission_key="manage_budgets",
        )

        assert reader.has_grant(workspace_id=workspace.id, user_id=user.id, permission_key="manage_budgets")

    def test_unrelated_direct_grant_does_not_resolve(self, reader, workspace_factory, user_factory) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePermissionGrant,
        )

        workspace = workspace_factory()
        user = user_factory()
        WorkspacePermissionGrant.objects.create(
            workspace=workspace,
            user=user,
            permission_key="manage_events",
        )

        assert not reader.has_grant(workspace_id=workspace.id, user_id=user.id, permission_key="manage_budgets")

    def test_direct_grant_in_other_workspace_does_not_leak(self, reader, workspace_factory, user_factory) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePermissionGrant,
        )

        target_workspace = workspace_factory()
        other_workspace = workspace_factory()
        user = user_factory()
        WorkspacePermissionGrant.objects.create(
            workspace=other_workspace,
            user=user,
            permission_key="manage_budgets",
        )

        assert not reader.has_grant(
            workspace_id=target_workspace.id,
            user_id=user.id,
            permission_key="manage_budgets",
        )


@pytest.mark.django_db
class TestGroupMediatedGrants:
    def test_group_grant_resolves_for_member(self, reader, workspace_factory, user_factory) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroup,
            WorkspaceGroupMembership,
            WorkspacePermissionGrant,
        )

        workspace = workspace_factory()
        user = user_factory()
        group = WorkspaceGroup.objects.create(workspace=workspace, name="Finance")
        WorkspaceGroupMembership.objects.create(group=group, user=user)
        WorkspacePermissionGrant.objects.create(workspace=workspace, group=group, permission_key="manage_budgets")

        assert reader.has_grant(workspace_id=workspace.id, user_id=user.id, permission_key="manage_budgets")

    def test_group_grant_in_other_workspace_does_not_leak(self, reader, workspace_factory, user_factory) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroup,
            WorkspaceGroupMembership,
            WorkspacePermissionGrant,
        )

        target_workspace = workspace_factory()
        other_workspace = workspace_factory()
        user = user_factory()
        other_group = WorkspaceGroup.objects.create(workspace=other_workspace, name="Other Finance")
        WorkspaceGroupMembership.objects.create(group=other_group, user=user)
        WorkspacePermissionGrant.objects.create(
            workspace=other_workspace, group=other_group, permission_key="manage_budgets"
        )

        assert not reader.has_grant(
            workspace_id=target_workspace.id,
            user_id=user.id,
            permission_key="manage_budgets",
        )

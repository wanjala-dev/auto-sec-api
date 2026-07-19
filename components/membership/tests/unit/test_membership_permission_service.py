"""Unit tests for :func:`membership_has_permission`.

Covers the three grant sources in isolation:

1. Role permissions via the ``workspace_role`` FK.
2. Legacy-role fallback for memberships created before Phase 1b (FK null).
3. Direct-user and group-mediated ``WorkspacePermissionGrant`` rows.

Ownership is intentionally *not* checked here — that's the DRF permission
class's job. These tests confirm the grant-resolution layer by itself.
"""

from __future__ import annotations

import pytest

from components.membership.application.services.membership_permission_service import (
    membership_has_permission,
)


@pytest.fixture
def _seed_system_roles(db):
    """Ensure the ``0016`` system roles exist for these tests.

    pytest skips migrations, so the seed data migration doesn't run. We
    materialize just the rows the service needs to resolve.
    """
    from infrastructure.persistence.workspaces.models import WorkspaceRole

    seeds = [
        ("owner", ["manage_settings", "manage_budgets", "view_budgets"]),
        ("admin", ["manage_settings", "manage_budgets", "view_budgets"]),
        ("viewer", ["view_reports"]),
        ("member", ["view_budgets", "view_donations"]),
    ]
    for slug, permissions in seeds:
        WorkspaceRole.objects.update_or_create(
            workspace=None,
            slug=slug,
            defaults={
                "name": slug.title(),
                "description": f"Seed for test: {slug}",
                "permissions": list(permissions),
                "is_system": True,
            },
        )


@pytest.fixture
def active_membership(db, workspace_factory, user_factory):
    """Return a factory that creates an ACTIVE ``WorkspaceMembership``."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    def _create(*, role="member", workspace_role=None, user=None, workspace=None):
        workspace = workspace or workspace_factory()
        user = user or user_factory()
        return WorkspaceMembership.objects.create(
            workspace=workspace,
            user=user,
            role=role,
            workspace_role=workspace_role,
            persona="contributor",
            status=WorkspaceMembership.Status.ACTIVE,
        )

    return _create


@pytest.mark.django_db
class TestReturnsFalseOnDegenerateInput:
    def test_none_membership(self) -> None:
        assert membership_has_permission(None, "manage_budgets") is False

    def test_empty_permission_key(self, active_membership) -> None:
        membership = active_membership()
        assert membership_has_permission(membership, "") is False


@pytest.mark.django_db
class TestResolvesViaWorkspaceRoleFk:
    """Phase 1b onward — FK is authoritative when present."""

    def test_fk_covers_key(self, _seed_system_roles, active_membership) -> None:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        admin_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="admin")
        membership = active_membership(role="admin", workspace_role=admin_role)

        assert membership_has_permission(membership, "manage_budgets") is True

    def test_fk_does_not_cover_key(self, _seed_system_roles, active_membership) -> None:
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        membership = active_membership(role="viewer", workspace_role=viewer_role)

        assert membership_has_permission(membership, "manage_budgets") is False

    def test_fk_beats_stale_legacy_role(self, _seed_system_roles, active_membership) -> None:
        """If FK disagrees with the legacy string, FK wins (it's the Phase 2+ truth)."""
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        # Contrived stale row: legacy role=admin but FK=viewer. Phase 2 trusts FK.
        membership = active_membership(role="admin", workspace_role=viewer_role)

        assert membership_has_permission(membership, "manage_budgets") is False


@pytest.mark.django_db
class TestFallsBackToLegacyRoleStringWhenFkNull:
    """Pre-Phase-1b rows still authorize correctly through the migration window."""

    def test_legacy_admin_covers_manage_budgets(
        self, _seed_system_roles, active_membership
    ) -> None:
        membership = active_membership(role="admin", workspace_role=None)
        assert membership_has_permission(membership, "manage_budgets") is True

    def test_legacy_viewer_does_not_cover_manage_budgets(
        self, _seed_system_roles, active_membership
    ) -> None:
        membership = active_membership(role="viewer", workspace_role=None)
        assert membership_has_permission(membership, "manage_budgets") is False

    def test_legacy_role_unknown_slug_denies(
        self, _seed_system_roles, active_membership
    ) -> None:
        membership = active_membership(role="nonsense", workspace_role=None)
        assert membership_has_permission(membership, "manage_budgets") is False

    def test_legacy_role_empty_string_denies(
        self, _seed_system_roles, active_membership
    ) -> None:
        membership = active_membership(role="", workspace_role=None)
        assert membership_has_permission(membership, "manage_budgets") is False


@pytest.mark.django_db
class TestDirectUserGrantsOverrideRoleBundle:
    """``WorkspacePermissionGrant`` is the escape hatch for one-off capabilities."""

    def test_direct_user_grant_authorizes_viewer(
        self, _seed_system_roles, active_membership
    ) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePermissionGrant,
            WorkspaceRole,
        )

        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        membership = active_membership(role="viewer", workspace_role=viewer_role)
        WorkspacePermissionGrant.objects.create(
            workspace=membership.workspace,
            user=membership.user,
            permission_key="manage_budgets",
        )

        assert membership_has_permission(membership, "manage_budgets") is True

    def test_unrelated_direct_grant_does_not_authorize(
        self, _seed_system_roles, active_membership
    ) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspacePermissionGrant,
            WorkspaceRole,
        )

        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        membership = active_membership(role="viewer", workspace_role=viewer_role)
        WorkspacePermissionGrant.objects.create(
            workspace=membership.workspace,
            user=membership.user,
            permission_key="manage_events",
        )

        assert membership_has_permission(membership, "manage_budgets") is False


@pytest.mark.django_db
class TestGroupMediatedGrants:
    """Permissions on a ``WorkspaceGroup`` authorize every member of that group."""

    def test_group_grant_authorizes_member(
        self, _seed_system_roles, active_membership
    ) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroup,
            WorkspaceGroupMembership,
            WorkspacePermissionGrant,
            WorkspaceRole,
        )

        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        membership = active_membership(role="viewer", workspace_role=viewer_role)

        group = WorkspaceGroup.objects.create(
            workspace=membership.workspace,
            name="Finance Team",
        )
        WorkspaceGroupMembership.objects.create(group=group, user=membership.user)
        WorkspacePermissionGrant.objects.create(
            workspace=membership.workspace,
            group=group,
            permission_key="manage_budgets",
        )

        assert membership_has_permission(membership, "manage_budgets") is True

    def test_group_grant_on_different_workspace_does_not_leak(
        self, _seed_system_roles, active_membership, workspace_factory
    ) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroup,
            WorkspaceGroupMembership,
            WorkspacePermissionGrant,
            WorkspaceRole,
        )

        viewer_role = WorkspaceRole.objects.get(workspace__isnull=True, slug="viewer")
        membership = active_membership(role="viewer", workspace_role=viewer_role)

        # Group in a DIFFERENT workspace with the right permission — must NOT leak.
        other_workspace = workspace_factory()
        other_group = WorkspaceGroup.objects.create(
            workspace=other_workspace,
            name="Other Finance Team",
        )
        WorkspaceGroupMembership.objects.create(group=other_group, user=membership.user)
        WorkspacePermissionGrant.objects.create(
            workspace=other_workspace,
            group=other_group,
            permission_key="manage_budgets",
        )

        assert membership_has_permission(membership, "manage_budgets") is False

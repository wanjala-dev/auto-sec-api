"""Integration tests — admin endpoints for the permission matrix UI.

Covers:

- ``GET /workspaces/<ws>/members/effective-permissions/``
  Returns every active membership with role-derived and direct-grant
  permission sets separated, plus is_owner flag. Drives the matrix.

- ``PATCH /workspaces/<ws>/members/<user>/role/``
  Reassigns a member's ``WorkspaceMembership.workspace_role`` FK.
  Gated on ``manage_users``. Owner's role cannot be changed here.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _make_membership(workspace, user, *, role_slug):
    from infrastructure.persistence.workspaces.models import (
        WorkspaceMembership,
        WorkspaceRole,
    )

    role_obj = WorkspaceRole.objects.get(workspace__isnull=True, slug=role_slug)
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role_slug,
        workspace_role=role_obj,
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )


# ── effective-permissions endpoint ──────────────────────────────────


def _effective_url(workspace):
    return reverse(
        "workspace-members-effective-permissions",
        kwargs={"workspace_id": str(workspace.id)},
    )


class TestEffectivePermissionsAuthorization:
    def test_non_admin_is_denied(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        member = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, member, role_slug="member")

        api_client.force_authenticate(user=member)
        response = api_client.get(_effective_url(workspace))

        assert response.status_code == 403


class TestEffectivePermissionsShape:
    def test_rows_split_role_and_direct_keys(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        from infrastructure.persistence.workspaces.models import WorkspacePermissionGrant

        owner = user_factory()
        finance_user = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, finance_user, role_slug="finance")
        # Extra direct grant on top of the role bundle.
        WorkspacePermissionGrant.objects.create(
            workspace=workspace,
            user=finance_user,
            permission_key="manage_events",
        )

        api_client.force_authenticate(user=owner)
        response = api_client.get(_effective_url(workspace))

        assert response.status_code == 200
        members = {row["user_id"]: row for row in response.data["members"]}

        owner_row = members[str(owner.id)]
        assert owner_row["is_owner"] is True
        # Owner's row surfaces the owner system-role bundle via the FK
        # if ensure_workspace_membership assigned one; we don't assert
        # its content here because workspace_factory doesn't wire it.

        finance_row = members[str(finance_user.id)]
        assert finance_row["is_owner"] is False
        assert finance_row["role_slug"] == "finance"
        # finance bundle from 0016 seed
        assert "manage_budgets" in finance_row["role_permissions"]
        assert "manage_donations" in finance_row["role_permissions"]
        # direct grant surfaces separately from role
        assert finance_row["direct_permissions"] == ["manage_events"]


# ── set-member-role endpoint ────────────────────────────────────────


def _role_url(workspace, user):
    return reverse(
        "workspace-member-role",
        kwargs={"workspace_id": str(workspace.id), "user_id": str(user.id)},
    )


class TestSetMemberRoleAuthorization:
    def test_non_admin_is_denied(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        target = user_factory()
        non_admin = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")
        _make_membership(workspace, non_admin, role_slug="member")

        api_client.force_authenticate(user=non_admin)
        response = api_client.patch(
            _role_url(workspace, target),
            {"role_slug": "finance"},
            format="json",
        )

        assert response.status_code == 403


class TestSetMemberRoleHappyPath:
    def test_admin_can_promote_member_to_finance(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceMembership,
            WorkspaceRole,
        )

        owner = user_factory()
        admin = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, admin, role_slug="admin")
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=admin)
        response = api_client.patch(
            _role_url(workspace, target),
            {"role_slug": "finance"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["role_slug"] == "finance"

        membership = WorkspaceMembership.objects.get(
            workspace=workspace, user=target
        )
        finance_role = WorkspaceRole.objects.get(
            workspace__isnull=True, slug="finance"
        )
        assert membership.workspace_role_id == finance_role.id
        # Legacy string only syncs for slugs that match the TextChoices.
        # "finance" is not one, so the string stays at what it was.
        assert membership.role == "member"


class TestSetMemberRoleSyncsLegacyStringForKnownSlugs:
    def test_promotion_to_admin_syncs_legacy_role(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        admin = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, admin, role_slug="admin")
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=admin)
        response = api_client.patch(
            _role_url(workspace, target),
            {"role_slug": "admin"},
            format="json",
        )

        assert response.status_code == 200
        membership = WorkspaceMembership.objects.get(
            workspace=workspace, user=target
        )
        assert membership.role == "admin"  # legacy string updated


class TestSetMemberRoleValidation:
    def test_missing_role_slug_400(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            _role_url(workspace, target), {}, format="json"
        )

        assert response.status_code == 400

    def test_unknown_role_slug_400(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        target = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, target, role_slug="member")

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            _role_url(workspace, target),
            {"role_slug": "nonsense"},
            format="json",
        )

        assert response.status_code == 400

    def test_cannot_change_owner_role(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, owner, role_slug="owner")

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            _role_url(workspace, owner),
            {"role_slug": "finance"},
            format="json",
        )

        assert response.status_code == 409

    def test_non_member_target_404(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        stranger = user_factory()
        workspace = workspace_factory(owner=owner)

        api_client.force_authenticate(user=owner)
        response = api_client.patch(
            _role_url(workspace, stranger),
            {"role_slug": "finance"},
            format="json",
        )

        assert response.status_code == 404

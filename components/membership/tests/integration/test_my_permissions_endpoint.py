"""Integration tests — ``WorkspaceMyPermissionsView`` returns role+grants union.

The pre-Phase-2 implementation only returned direct + group grants,
which meant a user with (say) the seeded ``finance`` role but no
explicit grants saw an empty list and the frontend hid every button
even though the backend would have allowed them through.

The fix unions:

  1. Role-backed permissions (via ``workspace_role`` FK or the
     legacy-string fallback, matching ``HasWorkspacePermission`` exactly)
  2. Direct ``WorkspacePermissionGrant`` entries
  3. Group-mediated grants
  4. Workspace-owner structural override (full key set)
  5. Team-only compatibility (member bundle for users on a team but
     without a WorkspaceMembership row)
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


def _url(workspace):
    return reverse("workspace-my-permissions", kwargs={"workspace_id": str(workspace.id)})


class TestOwnerGetsFullKeySet:
    def test_owner_response(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        from components.membership.api.groups_controller import VALID_PERMISSION_KEYS

        owner = user_factory()
        workspace = workspace_factory(owner=owner)

        api_client.force_authenticate(user=owner)
        response = api_client.get(_url(workspace))

        assert response.status_code == 200
        assert response.data["is_owner"] is True
        assert set(response.data["permissions"]) == VALID_PERMISSION_KEYS


class TestRoleBackedPermissions:
    def test_finance_role_sees_its_bundle(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        finance_user = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, finance_user, role_slug="finance")

        api_client.force_authenticate(user=finance_user)
        response = api_client.get(_url(workspace))

        assert response.status_code == 200
        assert response.data["is_owner"] is False
        keys = set(response.data["permissions"])
        # finance seed carries exactly these keys
        assert "manage_budgets" in keys
        assert "manage_donations" in keys
        assert "manage_billing" in keys
        # finance does NOT carry campaign/event management
        assert "manage_campaigns" not in keys
        assert "manage_events" not in keys

    def test_viewer_role_sees_only_reports(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        viewer = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, viewer, role_slug="viewer")

        api_client.force_authenticate(user=viewer)
        response = api_client.get(_url(workspace))

        assert response.status_code == 200
        keys = set(response.data["permissions"])
        assert keys == {"view_reports"}


class TestDirectGrantUnionsWithRole:
    def test_direct_grant_adds_to_role_bundle(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        from infrastructure.persistence.workspaces.models import WorkspacePermissionGrant

        owner = user_factory()
        viewer = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, viewer, role_slug="viewer")
        WorkspacePermissionGrant.objects.create(
            workspace=workspace,
            user=viewer,
            permission_key="manage_budgets",
        )

        api_client.force_authenticate(user=viewer)
        response = api_client.get(_url(workspace))

        keys = set(response.data["permissions"])
        assert "view_reports" in keys        # from role
        assert "manage_budgets" in keys      # from direct grant


class TestTeamOnlyFallback:
    def test_team_only_user_sees_member_bundle(
        self, api_client, workspace_factory, user_factory, team_factory
    ) -> None:
        owner = user_factory()
        team_only_user = user_factory()
        workspace = workspace_factory(owner=owner)
        team_factory(workspace=workspace, members=[team_only_user])

        api_client.force_authenticate(user=team_only_user)
        response = api_client.get(_url(workspace))

        keys = set(response.data["permissions"])
        assert "view_budgets" in keys
        assert "view_donations" in keys
        assert "manage_budgets" not in keys  # member is read-only


class TestNonMemberGetsEmpty:
    def test_stranger_gets_empty_set(
        self, api_client, workspace_factory, user_factory
    ) -> None:
        owner = user_factory()
        stranger = user_factory()
        workspace = workspace_factory(owner=owner)

        api_client.force_authenticate(user=stranger)
        response = api_client.get(_url(workspace))

        assert response.status_code == 200
        assert response.data["permissions"] == []

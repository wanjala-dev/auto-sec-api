"""Authorization + tenant scoping for the workspace CRUD surface.

``GET /workspaces/`` and ``GET|PATCH|PUT|DELETE /workspaces/<id>/`` were the
last two views on the permissive ``IsUnauthenticatedOrAdminOrStaff`` class
sitting on top of an UNFILTERED workspace queryset. That combination made the
organization directory readable by anyone on the internet — no account, no
token — including every org's owner email and its full member roster, and let
any authenticated user mutate or delete any other tenant's organization.

These tests lock the member-only floor for the org record itself, mirroring
``test_workspace_setup_status_authz.py`` (the same defect class, fixed once
already on the setup-status funnel) and the finding-surface cross-tenant
isolation assertions.

Scoping the queryset is only half the fix: ``WorkspaceList`` caches its
FULLY-SERIALIZED payload, so a cache key without the caller in it would hand
user A's organizations straight to user B on the next request. The cache tests
below are load-bearing, not decoration.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

pytestmark = [pytest.mark.django_db]

LIST_URL = "/workspaces/"


def _detail_url(workspace) -> str:
    return f"/workspaces/{workspace.id}/"


def _add_member(workspace, user, *, role="viewer", status="active"):
    WorkspaceMembership = django_apps.get_model("workspaces", "WorkspaceMembership")
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        status=status,
    )


def _ids(payload) -> set[str]:
    rows = payload if isinstance(payload, list) else payload.get("results", payload)
    return {str(row["id"]) for row in rows}


class TestWorkspaceListAuthz:
    def test_anonymous_is_refused(self, api_client, workspace_factory):
        """The org directory must never be readable without an account."""
        workspace_factory()
        response = api_client.get(LIST_URL)
        assert response.status_code in (401, 403), (
            f"anonymous listed the organization directory (HTTP {response.status_code})"
        )

    def test_non_member_does_not_see_another_tenants_workspace(self, api_client, workspace_factory, user_factory):
        victim = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.get(LIST_URL)

        assert response.status_code == 200
        assert str(victim.id) not in _ids(response.json())

    def test_owner_sees_only_their_own_workspaces(self, api_client, workspace_factory):
        mine = workspace_factory()
        theirs = workspace_factory()
        api_client.force_authenticate(user=mine.workspace_owner)

        response = api_client.get(LIST_URL)

        assert response.status_code == 200
        visible = _ids(response.json())
        assert str(mine.id) in visible
        assert str(theirs.id) not in visible

    def test_active_member_sees_the_workspace_they_belong_to(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        member = user_factory()
        _add_member(workspace, member)
        api_client.force_authenticate(user=member)

        response = api_client.get(LIST_URL)

        assert response.status_code == 200
        assert str(workspace.id) in _ids(response.json())

    def test_list_cache_does_not_leak_across_users(self, api_client, workspace_factory, user_factory):
        """A shared cache key would serve the first caller's orgs to the second."""
        mine = workspace_factory()
        outsider = user_factory()

        api_client.force_authenticate(user=mine.workspace_owner)
        first = api_client.get(LIST_URL)
        assert first.status_code == 200
        assert str(mine.id) in _ids(first.json())

        api_client.force_authenticate(user=outsider)
        second = api_client.get(LIST_URL)

        assert second.status_code == 200
        assert str(mine.id) not in _ids(second.json()), (
            "the workspace list cache served one user's organizations to another"
        )


class TestWorkspaceDetailAuthz:
    def test_anonymous_is_refused(self, api_client, workspace_factory):
        workspace = workspace_factory()
        response = api_client.get(_detail_url(workspace))
        assert response.status_code in (401, 403), (
            f"anonymous read an organization's detail (HTTP {response.status_code})"
        )

    def test_non_member_gets_404_not_403(self, api_client, workspace_factory, user_factory):
        """404, never 403 — a 403 confirms the organization exists."""
        victim = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.get(_detail_url(victim))

        assert response.status_code == 404

    def test_owner_reads_their_own_workspace(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        response = api_client.get(_detail_url(workspace))

        assert response.status_code == 200
        assert str(response.json()["id"]) == str(workspace.id)

    def test_active_member_reads_the_workspace(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        member = user_factory()
        _add_member(workspace, member)
        api_client.force_authenticate(user=member)

        response = api_client.get(_detail_url(workspace))

        assert response.status_code == 200

    def test_non_member_cannot_patch_another_tenants_workspace(self, api_client, workspace_factory, user_factory):
        victim = workspace_factory(workspace_name="Victim Org")
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.patch(_detail_url(victim), {"workspace_name": "Owned"}, format="json")

        assert response.status_code == 404
        victim.refresh_from_db()
        assert victim.workspace_name == "Victim Org"

    def test_non_member_cannot_delete_another_tenants_workspace(self, api_client, workspace_factory, user_factory):
        victim = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.delete(_detail_url(victim))

        assert response.status_code == 404
        Workspace = django_apps.get_model("workspaces", "Workspace")
        assert Workspace.objects.filter(id=victim.id).exists()

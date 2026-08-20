"""Tenant isolation for the workspace preferences / cards / operations surface.

Found by the QA sweep on the live cluster, 2026-08-19. Three sibling views —
``WorkspacePreferencesView``, ``WorkspaceCardView`` and
``WorkspaceOperationsView`` — were gated by
``components.workspace.api.workspace_permissions.IsUnauthenticatedOrAdminOrStaff``::

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated

Both branches are the bug:

* **Every safe method returns ``True`` for anyone** — so an ANONYMOUS
  ``GET /workspaces/<id>/preferences/`` returned another organization's
  settings, and the unscoped ``GET /workspaces/preferences/`` returned
  *every* organization's row (a cross-tenant enumeration of workspace ids).
* **Every unsafe method needs only "some account is logged in"** — no
  membership check, no object-level check. autosec's pooled tier has no
  database boundary behind that gate (``/tenancy`` §1.4), so the workspace
  id in the URL was the only thing being trusted.

The destructive half is the one that matters. Both ``delete()`` handlers
fetched the **Workspace** rather than the preference/card they are named
for::

    def delete(self, request, workspace=None):
        preference = get_object_or_404(Workspace, id=workspace)
        preference.delete()

``Workspace`` is a plain ``models.Model`` — that is a real cascading DELETE,
not a tombstone. Reproduced live against throwaway orgs the sweep created:
user A, who could not even *read* org B (``GET /workspaces/<B>/`` → 404),
ran ``DELETE /workspaces/<B>/preferences/`` → ``200 {"data":"Item Deleted"}``
and org B's row plus all of its teams were gone from the database. The
``cards`` route did the same thing on a second org. Registration is open, so
the blast radius was every organization on the pooled console.

The fix is two-part and this module pins both halves:

1. ``IsAuthenticated + IsActiveWorkspaceMember`` on all three views, which
   also fails the *unscoped* collection routes closed (no workspace kwarg →
   ``user_is_active_workspace_member(user, None)`` is ``False``).
2. ``delete()`` removes the preference / card row it is named for. Deleting
   an organization stays on ``WorkspaceDetail.destroy``, behind
   ``IsWorkspaceAdminOfObject`` — see ``test_workspace_detail_write_authz``.

Every denial below asserts the EFFECT (the org still exists, the settings are
unchanged) as well as the status code, so a future change to which code is
returned can never quietly turn a deny into an allow.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

pytestmark = [pytest.mark.django_db]


def _workspace_model():
    return django_apps.get_model("workspaces", "Workspace")


def _prefs_url(workspace) -> str:
    return f"/workspaces/{workspace.id}/preferences/"


def _cards_url(workspace) -> str:
    return f"/workspaces/{workspace.id}/cards/"


def _operations_url(workspace) -> str:
    return f"/workspaces/{workspace.id}/operations/"


class TestWorkspaceSettingsSurfaceIsNotAnOrgDeleteButton:
    """The reported defect: `/preferences/` and `/cards/` DELETE the whole org."""

    def test_non_member_cannot_delete_org_via_preferences(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.delete(_prefs_url(workspace))

        assert response.status_code in (403, 404)
        assert _workspace_model().objects.filter(id=workspace.id).exists()

    def test_non_member_cannot_delete_org_via_cards(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.delete(_cards_url(workspace))

        assert response.status_code in (403, 404)
        assert _workspace_model().objects.filter(id=workspace.id).exists()

    def test_owner_deleting_preferences_does_not_delete_the_org(self, api_client, workspace_factory):
        """Even for the owner, `/preferences/` must not be an org-delete button.

        Org deletion is ``DELETE /workspaces/<id>/``, gated by
        ``IsWorkspaceAdminOfObject``. A settings route that silently destroys
        the tenant is a footgun regardless of who pulls it.
        """
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        api_client.delete(_prefs_url(workspace))

        assert _workspace_model().objects.filter(id=workspace.id).exists()

    def test_owner_deleting_cards_does_not_delete_the_org(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        api_client.delete(_cards_url(workspace))

        assert _workspace_model().objects.filter(id=workspace.id).exists()


class TestWorkspaceSettingsSurfaceCrossTenantWrites:
    def test_non_member_cannot_patch_another_orgs_preferences(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.patch(_prefs_url(workspace), {"settings": {"pwned": True}}, format="json")

        assert response.status_code in (403, 404)
        assert "pwned" not in str(_read_settings(api_client, workspace))

    def test_non_member_cannot_patch_another_orgs_cards(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.patch(_cards_url(workspace), {"title": "PWNED"}, format="json")

        assert response.status_code in (403, 404)


class TestWorkspaceSettingsSurfaceReads:
    """Safe methods were unauthenticated. They are workspace-scoped data."""

    def test_anonymous_cannot_read_another_orgs_preferences(self, api_client, workspace_factory):
        workspace = workspace_factory()

        response = api_client.get(_prefs_url(workspace))

        assert response.status_code in (401, 403, 404)
        assert str(workspace.id) not in response.content.decode()

    def test_non_member_cannot_read_another_orgs_preferences(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.get(_prefs_url(workspace))

        assert response.status_code in (401, 403, 404)
        assert str(workspace.id) not in response.content.decode()

    def test_anonymous_cannot_enumerate_every_orgs_preferences(self, api_client, workspace_factory):
        """`GET /workspaces/preferences/` (no workspace) dumped every row.

        The unscoped collection is the enumeration half of the same hole: it
        names every organization id on the console. There is no legitimate
        caller for it, so the membership gate — which resolves no workspace
        here and therefore denies — is the right answer.
        """
        workspace = workspace_factory()

        response = api_client.get("/workspaces/preferences/")

        assert response.status_code in (401, 403, 404)
        assert str(workspace.id) not in response.content.decode()

    def test_anonymous_cannot_read_another_orgs_operations(self, api_client, workspace_factory):
        workspace = workspace_factory()

        response = api_client.get(_operations_url(workspace))

        assert response.status_code in (401, 403, 404)

    def test_member_can_still_read_their_own_preferences(self, api_client, workspace_factory):
        """The gate must not have broken the legitimate caller."""
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        response = api_client.get(_prefs_url(workspace))

        assert response.status_code == 200
        assert str(workspace.id) in response.content.decode()

    def test_member_can_still_patch_their_own_preferences(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        response = api_client.patch(_prefs_url(workspace), {"settings": {"story": False}}, format="json")

        assert response.status_code == 200


def _read_settings(api_client, workspace):
    """Read the row back as its owner — the deny above must not have written."""
    api_client.force_authenticate(user=workspace.workspace_owner)
    return api_client.get(_prefs_url(workspace)).content.decode()

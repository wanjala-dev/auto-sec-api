"""Object-level authorization for the workspace detail write surface.

``PATCH/PUT/DELETE /workspaces/<id>/`` (``WorkspaceDetail``) was gated only
by ``IsUnauthenticatedOrAdminOrStaff``, whose unsafe-method branch is
``return request.user.is_authenticated`` — no object-level check at all —
over the unscoped ``get_all_workspaces_with_relations()`` queryset. Any
authenticated account on the pooled console could therefore rewrite, or
hard-delete, any other organization's row (``Workspace`` is a plain
``models.Model``: ``destroy`` is a real ``DELETE`` that cascades, not a
tombstone).

**Two independent gates now stand between a caller and a write, and this
module pins both — they are complementary, not duplicates:**

1. **The tenant boundary** — the queryset is scoped to organizations the
   caller owns or holds an ACTIVE membership in, so a NON-MEMBER never gets
   an object at all: ``get_object()`` raises **404**, not 403. (A 403 would
   confirm the organization exists.) That scoping landed separately, with the
   fix for the world-readable org directory.
2. **The role boundary inside the tenant** — ``IsWorkspaceAdminOfObject`` on
   the write actions. Scoping alone admits EVERY active member, so without
   this a viewer-role member could still rewrite or hard-delete the org. That
   gate is what this module was opened for, and
   ``test_viewer_member_cannot_patch`` is its load-bearing assertion.

Each denial below asserts the EFFECT (the row is unchanged, or still exists)
as well as the status code, so a future change to which code is returned can
never quietly turn a deny into an allow.

Same spirit as ``test_workspace_setup_status_authz.py``, which locked the
member-only floor for the setup-status read.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

pytestmark = [pytest.mark.django_db]


def _url(workspace) -> str:
    return reverse("workspace-detail", kwargs={"pk": str(workspace.id)})


def _workspace_model():
    return django_apps.get_model("workspaces", "Workspace")


def _membership_model():
    return django_apps.get_model("workspaces", "WorkspaceMembership")


class TestWorkspaceDetailWriteAuthz:
    def test_non_member_cannot_patch_another_org(self, api_client, workspace_factory, user_factory):
        """The reported defect: a stranger's PATCH returned 200 and persisted.

        404 rather than 403: the tenant-scoped queryset means a non-member is
        never handed the object, so the denial happens before the role gate is
        ever consulted. Either code is a deny; the row not changing is the
        assertion that actually matters.
        """
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.patch(_url(workspace), {"workspace_story": "PWNED"}, format="json")

        assert response.status_code == 404
        workspace.refresh_from_db()
        assert workspace.workspace_story != "PWNED"

    def test_non_member_cannot_delete_another_org(self, api_client, workspace_factory, user_factory):
        """The reported defect: a stranger's DELETE returned 204 and the row was gone."""
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.delete(_url(workspace))

        assert response.status_code == 404
        assert _workspace_model().objects.filter(id=workspace.id).exists()

    def test_anonymous_cannot_patch(self, api_client, workspace_factory):
        workspace = workspace_factory()

        response = api_client.patch(_url(workspace), {"workspace_story": "PWNED"}, format="json")

        assert response.status_code in (401, 403)
        workspace.refresh_from_db()
        assert workspace.workspace_story != "PWNED"

    def test_viewer_member_cannot_patch(self, api_client, workspace_factory, user_factory):
        """Membership alone is not enough — org settings are an admin surface."""
        workspace = workspace_factory()
        viewer = user_factory()
        _membership_model().objects.create(workspace=workspace, user=viewer, role="viewer", status="active")
        api_client.force_authenticate(user=viewer)

        response = api_client.patch(_url(workspace), {"workspace_story": "PWNED"}, format="json")

        assert response.status_code == 403
        workspace.refresh_from_db()
        assert workspace.workspace_story != "PWNED"

    def test_owner_can_patch_their_own_org(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        response = api_client.patch(_url(workspace), {"workspace_story": "our story"}, format="json")

        assert response.status_code == 200
        workspace.refresh_from_db()
        assert workspace.workspace_story == "our story"

    def test_admin_member_can_patch(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        admin = user_factory()
        _membership_model().objects.create(workspace=workspace, user=admin, role="admin", status="active")
        api_client.force_authenticate(user=admin)

        response = api_client.patch(_url(workspace), {"workspace_story": "admin edit"}, format="json")

        assert response.status_code == 200
        workspace.refresh_from_db()
        assert workspace.workspace_story == "admin edit"

    def test_owner_can_still_delete_their_own_org(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)

        response = api_client.delete(_url(workspace))

        assert response.status_code == 204
        assert not _workspace_model().objects.filter(id=workspace.id).exists()

    def test_non_member_read_is_still_denied(self, api_client, workspace_factory, user_factory):
        """The write gate must not have WIDENED the read.

        This assertion was inverted when the branch was written: back then the
        detail read was unscoped, so it pinned an outsider GET at 200 to show
        the read path had deliberately not been touched. The read has since
        been scoped, so 200 here would now mean the very disclosure that fix
        closed. It is kept — pointed the other way — because it is still the
        right guard rail: it proves the write gate neither leaked into
        ``retrieve`` nor loosened it.
        """
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.get(_url(workspace))

        assert response.status_code == 404

    def test_member_read_still_works_under_the_write_gate(self, api_client, workspace_factory, user_factory):
        """The other direction: the write gate must not have NARROWED the read.

        A viewer-role member is denied writes by ``IsWorkspaceAdminOfObject``.
        They must still be able to READ the organization they belong to — the
        gate is selected per action, so a leak into ``retrieve`` would lock
        every non-admin member out of their own org.
        """
        workspace = workspace_factory()
        viewer = user_factory()
        _membership_model().objects.create(workspace=workspace, user=viewer, role="viewer", status="active")
        api_client.force_authenticate(user=viewer)

        response = api_client.get(_url(workspace))

        assert response.status_code == 200

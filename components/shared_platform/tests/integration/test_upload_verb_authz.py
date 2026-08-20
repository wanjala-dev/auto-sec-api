"""Verb + authorization surface of the file-upload routes.

Two defects on one ``permission_classes`` tuple,
``(IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)``:

``IsOwnerOrReadOnly`` (``components/shared_platform/api/permissions.py``) is
``has_object_permission``-ONLY, and it returns ``True`` for SAFE_METHODS. DRF
never invokes an object hook on a LIST route, so on the collection it
contributes literally nothing; on the detail route it waves every read
through. ``IsAuthenticatedOrReadOnly`` then permits anonymous SAFE_METHODS.
The two compose to **fully public reads**.

Confirmed live, no ``Authorization`` header:

* ``GET /upload/``    -> **200**, DRF page envelope, returning 100% of the
  ``File`` rows in the database. ``get_queryset()`` starts from
  ``File.objects.all()`` and applies ``workspace_id`` only when the CLIENT
  passes ``?workspace_id=`` — an opt-in filter is not a tenant boundary.
* ``GET /upload/1/``  -> **200**.

``FileSerializer`` ships ``pdf_text`` (the full extracted text of an uploaded
document), ``file``/``file_path``/``url`` (storage locations, rendered as an
absolute media URL), and ``owner``. Primary keys are sequential integers, so
the collection is trivially enumerable. autosec is single-database (ADR 0028):
the queryset scoping IS the tenant boundary.

Separately, the collection route's action map wires ``put``/``patch``/
``delete`` onto a URL with **no pk**::

    path("", FileUploadView.as_view({... "put": "update", "delete": "destroy"}))

``update``/``destroy`` call ``get_object()``, which reads
``self.kwargs[lookup_url_kwarg]``. There is no ``pk`` to read, so they raise
``AssertionError: Expected view FileUploadView to be called with a URL keyword
argument named "pk"`` — an unhandled **500** where a **405** belongs, remotely
triggerable by any authenticated caller. Those verbs already exist, correctly,
on the ``<int:pk>/`` detail routes.

Fixes, both narrowing rather than patching:

* the collection action map becomes ``{"get": "list", "post": "create"}`` — the
  three broken verbs are **405**, structurally, not merely denied;
* reads require authentication, and BOTH routes scope the queryset server-side
  to files the caller owns or that live in a workspace they hold an ACTIVE
  membership in. Writes keep ``IsOwnerOrReadOnly``, which is now reachable.

Foreign-tenant denials are **404**: the row is filtered out before
``get_object()``, so the response does not confirm the file exists.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

pytestmark = [pytest.mark.django_db]


def _file_model():
    return django_apps.get_model("uploads", "File")


def _membership_model():
    return django_apps.get_model("workspaces", "WorkspaceMembership")


def _join(workspace, user):
    Membership = _membership_model()
    return Membership.objects.create(
        workspace=workspace,
        user=user,
        role="viewer",
        status=Membership.Status.ACTIVE,
    )


class TestCollectionReadRequiresAuth:
    def test_anonymous_list_is_refused(self, api_client, file_factory):
        """The reported defect: 200 with every File row in the database."""
        file_factory()

        response = api_client.get("/upload/")

        assert response.status_code == 401

    def test_authenticated_list_is_scoped_to_the_caller(
        self, api_client, file_factory, user_factory, workspace_factory
    ):
        workspace = workspace_factory()
        member = user_factory()
        _join(workspace, member)
        mine = file_factory(owner=member, workspace_id=str(workspace.id))
        theirs = file_factory(workspace_id=str(workspace_factory().id))
        api_client.force_authenticate(user=member)

        response = api_client.get("/upload/")

        assert response.status_code == 200
        returned = {row["pk"] for row in response.data["results"]}
        assert mine.pk in returned
        assert theirs.pk not in returned

    def test_client_supplied_workspace_id_cannot_widen_the_scope(
        self, api_client, file_factory, user_factory, workspace_factory
    ):
        """``?workspace_id=`` is a convenience filter. It must only ever narrow
        what the caller may already see — never select a foreign tenant.
        """
        foreign_workspace = workspace_factory()
        theirs = file_factory(workspace_id=str(foreign_workspace.id))
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.get(f"/upload/?workspace_id={foreign_workspace.id}")

        assert response.status_code == 200
        assert theirs.pk not in {row["pk"] for row in response.data["results"]}


class TestCollectionWriteVerbsAreGone:
    """PUT/PATCH/DELETE on a pk-less route cannot address a row; they 500."""

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_authenticated_write_on_the_collection_is_not_allowed(self, api_client, user_factory, file_factory, method):
        owned = file_factory(owner=user_factory())
        api_client.force_authenticate(user=owned.owner)

        response = getattr(api_client, method)("/upload/", {}, format="json")

        assert response.status_code == 405
        assert _file_model().objects.filter(pk=owned.pk).exists()

    def test_authenticated_delete_on_the_collection_is_not_allowed(self, api_client, user_factory, file_factory):
        owned = file_factory(owner=user_factory())
        api_client.force_authenticate(user=owned.owner)

        response = api_client.delete("/upload/")

        assert response.status_code == 405
        assert _file_model().objects.filter(pk=owned.pk).exists()


class TestDetailReadRequiresAuthAndTenancy:
    @pytest.mark.parametrize("prefix", ["/upload", "/upload/upload"])
    def test_anonymous_detail_is_refused_on_every_mount(self, api_client, file_factory, prefix):
        """The same view is routed twice. A gate on one mount and not the other
        leaves the file readable through the sibling URL.
        """
        stored = file_factory()

        response = api_client.get(f"{prefix}/{stored.pk}/")

        assert response.status_code == 401

    def test_outsider_cannot_read_another_tenants_file(self, api_client, file_factory, user_factory, workspace_factory):
        stored = file_factory(workspace_id=str(workspace_factory().id))
        api_client.force_authenticate(user=user_factory())

        response = api_client.get(f"/upload/{stored.pk}/")

        assert response.status_code == 404

    def test_outsider_cannot_delete_another_tenants_file(
        self, api_client, file_factory, user_factory, workspace_factory
    ):
        stored = file_factory(workspace_id=str(workspace_factory().id))
        api_client.force_authenticate(user=user_factory())

        response = api_client.delete(f"/upload/{stored.pk}/")

        assert response.status_code == 404
        assert _file_model().objects.filter(pk=stored.pk).exists()

    def test_workspace_peer_cannot_delete_someone_elses_file(
        self, api_client, file_factory, user_factory, workspace_factory
    ):
        """403, not 404 — the peer may legitimately SEE the workspace document,
        so the denial is ownership, not tenancy.
        """
        workspace = workspace_factory()
        owner = user_factory()
        peer = user_factory()
        _join(workspace, owner)
        _join(workspace, peer)
        stored = file_factory(owner=owner, workspace_id=str(workspace.id))
        api_client.force_authenticate(user=peer)

        response = api_client.delete(f"/upload/{stored.pk}/")

        assert response.status_code == 403
        assert _file_model().objects.filter(pk=stored.pk).exists()


class TestIntendedSurfaceStillWorks:
    """``uploadsApi`` uses GET list, GET detail, POST create, DELETE detail."""

    def test_owner_can_read_own_file(self, api_client, file_factory, user_factory):
        stored = file_factory(owner=user_factory())
        api_client.force_authenticate(user=stored.owner)

        response = api_client.get(f"/upload/{stored.pk}/")

        assert response.status_code == 200
        assert response.data["pk"] == stored.pk

    def test_owner_can_delete_own_file(self, api_client, file_factory, user_factory):
        stored = file_factory(owner=user_factory())
        api_client.force_authenticate(user=stored.owner)

        response = api_client.delete(f"/upload/{stored.pk}/")

        assert response.status_code == 204
        assert not _file_model().objects.filter(pk=stored.pk).exists()

    def test_workspace_peer_can_read_a_workspace_document(
        self, api_client, file_factory, user_factory, workspace_factory
    ):
        """The document library is a workspace surface, not a private drawer —
        scoping must not shrink it to owner-only.
        """
        workspace = workspace_factory()
        owner = user_factory()
        peer = user_factory()
        _join(workspace, owner)
        _join(workspace, peer)
        stored = file_factory(owner=owner, workspace_id=str(workspace.id))
        api_client.force_authenticate(user=peer)

        response = api_client.get(f"/upload/{stored.pk}/")

        assert response.status_code == 200

    def test_owner_reaches_a_file_with_no_workspace(self, api_client, file_factory, user_factory):
        """``workspace_id`` is nullable. Scoping by workspace alone would strand
        the owner of an unattached upload.
        """
        stored = file_factory(owner=user_factory(), workspace_id=None)
        api_client.force_authenticate(user=stored.owner)

        response = api_client.get(f"/upload/{stored.pk}/")

        assert response.status_code == 200

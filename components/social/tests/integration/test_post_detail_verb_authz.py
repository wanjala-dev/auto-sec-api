"""Authorization for the standalone post-detail surface, ``/social/<pk>/``.

``PostDetail`` is a ``RetrieveUpdateDestroyAPIView`` that carried
``permission_classes = (RequiresFeatureFlag,)`` and nothing else.

``RequiresFeatureFlag`` answers exactly one question — "is the flag on for
this request" — and it defines no ``has_object_permission``, so DRF's default
object check passes. Declaring it ALONE replaces the project-wide default
(``IsAdminUser`` + ``IsAuthenticated``, ``api/settings/base.py``), so nothing
in the chain ever asked who was calling.

Worse, ``resolve_workspace_id_from_request`` honours a caller-supplied
``?workspace_id=`` BEFORE any authentication, so an anonymous caller picks the
workspace the flag is evaluated against. Against the live cluster, with a
workspace whose ``feature.social_feed`` rule is enabled::

    GET|PUT|PATCH|DELETE /social/999999999/?workspace_id=<that ws>
      -> 404 {"detail":"No Post matches the given query."}

401 without the parameter, 404 with it. The 401->404 shift is the proof: the
whole permission stack passed for an ANONYMOUS request and DRF reached
``get_object()``. Only the non-existent pk (deliberately chosen to keep the
probe's blast radius at zero) stopped a real edit or hard delete.

The identical sibling ``CommentDetail`` carries
``IsAuthenticatedOrReadOnly + IsOwnerOrReadOnly + RequiresFeatureFlag``, which
makes this a copy-paste omission rather than a policy.

Two gates now stand between a caller and a post, and this module pins both:

1. **Authentication + ownership** — ``IsAuthenticated`` and the existing
   ``IsOwnerOrReadOnly`` (``obj.author == request.user``). Reuse, not a new
   class: it is the same object rule the sibling already enforces.
2. **The tenant boundary** — the queryset is scoped to posts in workspaces the
   caller owns or holds an ACTIVE membership in, plus their own posts. autosec
   is single-database (ADR 0028), so an unscoped ``Post.objects`` reachable by
   integer pk IS a cross-tenant read; there is no database boundary behind it.

Every denial asserts the EFFECT — body unchanged, row still present — so a
later change to which status code is returned cannot quietly turn a deny into
an allow.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

pytestmark = [pytest.mark.django_db]


def _post_model():
    return django_apps.get_model("social", "Post")


def _membership_model():
    return django_apps.get_model("workspaces", "WorkspaceMembership")


def _url(post) -> str:
    return f"/social/{post.pk}/"


@pytest.fixture
def post_factory(db, user_factory):
    def _create(*, author=None, workspace=None, body="original body"):
        Post = _post_model()
        return Post.objects.create(
            author=author or user_factory(),
            body=body,
            workspace=workspace,
        )

    return _create


def _join(workspace, user):
    Membership = _membership_model()
    return Membership.objects.create(
        workspace=workspace,
        user=user,
        role="viewer",
        status=Membership.Status.ACTIVE,
    )


class TestAnonymousIsRefused:
    """The reported defect: no credentials, full read/write/delete."""

    def test_anonymous_get_is_refused(self, api_client, post_factory):
        post = post_factory()

        response = api_client.get(_url(post))

        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_anonymous_write_is_refused_and_body_survives(self, api_client, post_factory, method):
        post = post_factory(body="untouched")

        response = getattr(api_client, method)(_url(post), {"body": "PWNED"}, format="json")

        assert response.status_code == 401
        post.refresh_from_db()
        assert post.body == "untouched"

    def test_anonymous_delete_is_refused_and_row_survives(self, api_client, post_factory):
        post = post_factory()

        response = api_client.delete(_url(post))

        assert response.status_code == 401
        assert _post_model().objects.filter(pk=post.pk).exists()

    def test_anonymous_cannot_pivot_via_workspace_id_query_param(self, api_client, post_factory, workspace_factory):
        """The exact live repro: the flag is resolved against a caller-supplied
        workspace, so a flag-off deployment is not the control anyone assumed.
        """
        workspace = workspace_factory()
        post = post_factory(workspace=workspace, body="untouched")

        response = api_client.delete(f"{_url(post)}?workspace_id={workspace.id}")

        assert response.status_code == 401
        assert _post_model().objects.filter(pk=post.pk).exists()


class TestAuthenticatedNonAuthorIsRefused:
    def test_workspace_peer_cannot_edit_someone_elses_post(
        self, api_client, post_factory, workspace_factory, user_factory
    ):
        """403, not 404: the peer legitimately SEES the post (same workspace),
        so the denial is the ownership gate, not the tenant gate.
        """
        workspace = workspace_factory()
        author = user_factory()
        peer = user_factory()
        _join(workspace, author)
        _join(workspace, peer)
        post = post_factory(author=author, workspace=workspace, body="untouched")
        api_client.force_authenticate(user=peer)

        response = api_client.patch(_url(post), {"body": "PWNED"}, format="json")

        assert response.status_code == 403
        post.refresh_from_db()
        assert post.body == "untouched"

    def test_workspace_peer_cannot_delete_someone_elses_post(
        self, api_client, post_factory, workspace_factory, user_factory
    ):
        workspace = workspace_factory()
        author = user_factory()
        peer = user_factory()
        _join(workspace, author)
        _join(workspace, peer)
        post = post_factory(author=author, workspace=workspace)
        api_client.force_authenticate(user=peer)

        response = api_client.delete(_url(post))

        assert response.status_code == 403
        assert _post_model().objects.filter(pk=post.pk).exists()


class TestForeignTenantIsRefused:
    """404 rather than 403 — the tenant-scoped queryset never hands over the
    object, so the response does not confirm the post exists.
    """

    def test_outsider_cannot_read_another_tenants_post(self, api_client, post_factory, workspace_factory, user_factory):
        post = post_factory(workspace=workspace_factory())
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.get(_url(post))

        assert response.status_code == 404

    def test_outsider_cannot_delete_another_tenants_post(
        self, api_client, post_factory, workspace_factory, user_factory
    ):
        post = post_factory(workspace=workspace_factory())
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)

        response = api_client.delete(_url(post))

        assert response.status_code == 404
        assert _post_model().objects.filter(pk=post.pk).exists()


class TestIntendedSurfaceStillWorks:
    """The fix must narrow the gate, not remove the feature."""

    def test_author_can_read_own_post(self, api_client, post_factory, workspace_factory, user_factory):
        workspace = workspace_factory()
        author = user_factory()
        _join(workspace, author)
        post = post_factory(author=author, workspace=workspace)
        api_client.force_authenticate(user=author)

        response = api_client.get(_url(post))

        assert response.status_code == 200
        assert response.data["id"] == post.pk

    def test_author_can_edit_own_post(self, api_client, post_factory, workspace_factory, user_factory):
        workspace = workspace_factory()
        author = user_factory()
        _join(workspace, author)
        post = post_factory(author=author, workspace=workspace, body="before")
        api_client.force_authenticate(user=author)

        response = api_client.patch(_url(post), {"body": "after"}, format="json")

        assert response.status_code == 200
        post.refresh_from_db()
        assert post.body == "after"

    def test_author_can_delete_own_post(self, api_client, post_factory, workspace_factory, user_factory):
        workspace = workspace_factory()
        author = user_factory()
        _join(workspace, author)
        post = post_factory(author=author, workspace=workspace)
        api_client.force_authenticate(user=author)

        response = api_client.delete(_url(post))

        assert response.status_code == 204
        assert not _post_model().objects.filter(pk=post.pk).exists()

    def test_workspace_peer_can_read_a_workspace_post(self, api_client, post_factory, workspace_factory, user_factory):
        workspace = workspace_factory()
        author = user_factory()
        peer = user_factory()
        _join(workspace, author)
        _join(workspace, peer)
        post = post_factory(author=author, workspace=workspace)
        api_client.force_authenticate(user=peer)

        response = api_client.get(_url(post))

        assert response.status_code == 200

    def test_author_still_reaches_a_legacy_workspaceless_post(self, api_client, post_factory, user_factory):
        """Pre-feed posts have ``workspace = NULL``. Scoping by workspace alone
        would strand their authors, so the author leg of the filter is
        load-bearing, not belt-and-braces.
        """
        author = user_factory()
        post = post_factory(author=author, workspace=None)
        api_client.force_authenticate(user=author)

        response = api_client.get(_url(post))

        assert response.status_code == 200

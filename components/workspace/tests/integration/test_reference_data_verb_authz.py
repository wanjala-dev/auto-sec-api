"""Verb + authorization surface of the workspace REFERENCE-DATA routes.

Three routes, one root cause: ``IsUnauthenticatedOrAdminOrStaff``
(``components/workspace/api/workspace_permissions.py``) — a DIFFERENT class
from identity's same-named one — returns ``True`` for every SAFE_METHOD and
bare ``request.user.is_authenticated`` for every write, and defines no
``has_object_permission``. The name promises admin/staff; the body checks
neither. This is the class tracked as the "~10 workspace views on the same
permissive class" audit.

What that bought, confirmed live against the cluster with an ordinary
non-staff account that belongs to NO workspace at all:

* ``PUT|PATCH|DELETE /workspaces/category/detail/<pk>/`` -> **404**, not 403.
  DRF runs ``check_permissions()`` before ``get_object()``, so a 404 proves
  the gate passed and execution reached object lookup. A prior probe took the
  next step on a row it created itself: ``PATCH`` -> 200 with the new value
  echoed back, ``DELETE`` -> 204.
* ``PUT|PATCH|DELETE /workspaces/contribution-means/<pk>/`` -> **404**;
  ``POST`` on the collection -> **400** with a field error on ``name``, i.e.
  the gate handed the request to serializer validation.
* ``GET`` on all of them -> **200 anonymously**.

Both tables are GLOBAL: ``WorkspaceCategory`` and ``ContributionMeans`` have
no workspace FK and are served unscoped to every tenant. A DELETE removes the
row for every tenant simultaneously. The actor needed for that is weaker than
"a user of another tenant" — it is any logged-in account whatsoever.

``WorkspaceCommentList`` is the same shape from the other direction: its
``permission_classes`` are ``IsAuthenticatedOrReadOnly + IsOwnerOrReadOnly``,
and ``IsOwnerOrReadOnly`` is has_object_permission-ONLY, so on a list/create
route it never runs. That left anonymous reads of every tenant's comments,
and a POST gated by nothing but authentication — a second create path that
skips the ``IsWorkspaceFollowerOrMember`` check the real create endpoint
(``/workspaces/comment/create/``) enforces, using the *Get* serializer so it
does not even set ``author``.

The fix is the narrowest correct base class plus a real gate:

* the two reference tables become read-only views (``ListAPIView`` /
  ``RetrieveAPIView``, and a read-only viewset action map), so the write verbs
  are **405 Method Not Allowed** — the verb is gone, not merely guarded;
* every read requires authentication;
* the comment list is scoped to the caller's own workspaces.

405 is asserted deliberately: a 403 would mean the verb is still routed and
one permission edit away from returning. Each denial also asserts the row is
unchanged or still present.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

pytestmark = [pytest.mark.django_db]


def _category_model():
    return django_apps.get_model("workspaces", "WorkspaceCategory")


def _means_model():
    return django_apps.get_model("workspaces", "ContributionMeans")


def _comment_model():
    return django_apps.get_model("workspaces", "WorkspaceComment")


def _membership_model():
    return django_apps.get_model("workspaces", "WorkspaceMembership")


@pytest.fixture
def means(db):
    return _means_model().objects.create(name="Volunteering")


def _join(workspace, user):
    Membership = _membership_model()
    return Membership.objects.create(
        workspace=workspace,
        user=user,
        role="viewer",
        status=Membership.Status.ACTIVE,
    )


# ---------------------------------------------------------------------------
# WorkspaceCategory — global reference data
# ---------------------------------------------------------------------------


class TestWorkspaceCategoryWriteVerbsAreGone:
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_authenticated_user_cannot_rewrite_a_category(self, api_client, user_factory, workspace_category, method):
        api_client.force_authenticate(user=user_factory())

        response = getattr(api_client, method)(
            f"/workspaces/category/detail/{workspace_category.pk}/",
            {"name": "PWNED"},
            format="json",
        )

        assert response.status_code == 405
        workspace_category.refresh_from_db()
        assert workspace_category.name == "Education"

    def test_authenticated_user_cannot_delete_a_category(self, api_client, user_factory, workspace_category):
        api_client.force_authenticate(user=user_factory())

        response = api_client.delete(f"/workspaces/category/detail/{workspace_category.pk}/")

        assert response.status_code == 405
        assert _category_model().objects.filter(pk=workspace_category.pk).exists()

    def test_authenticated_user_cannot_inject_a_category(self, api_client, user_factory, workspace_category):
        api_client.force_authenticate(user=user_factory())
        before = _category_model().objects.count()

        response = api_client.post("/workspaces/category/", {"name": "[QA] injected"}, format="json")

        assert response.status_code == 405
        assert _category_model().objects.count() == before


class TestWorkspaceCategoryReadsRequireAuth:
    def test_anonymous_list_is_refused(self, api_client, workspace_category):
        assert api_client.get("/workspaces/category/").status_code == 401

    def test_anonymous_detail_is_refused(self, api_client, workspace_category):
        response = api_client.get(f"/workspaces/category/detail/{workspace_category.pk}/")

        assert response.status_code == 401

    def test_authenticated_list_still_works(self, api_client, user_factory, workspace_category):
        api_client.force_authenticate(user=user_factory())

        response = api_client.get("/workspaces/category/")

        assert response.status_code == 200

    def test_authenticated_detail_still_works(self, api_client, user_factory, workspace_category):
        api_client.force_authenticate(user=user_factory())

        response = api_client.get(f"/workspaces/category/detail/{workspace_category.pk}/")

        assert response.status_code == 200
        assert response.data["name"] == "Education"


# ---------------------------------------------------------------------------
# ContributionMeans — global reference data behind a ModelViewSet whose
# update/destroy were inherited and never considered
# ---------------------------------------------------------------------------


class TestContributionMeansWriteVerbsAreGone:
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_authenticated_user_cannot_rewrite_a_means(self, api_client, user_factory, means, method):
        api_client.force_authenticate(user=user_factory())

        response = getattr(api_client, method)(
            f"/workspaces/contribution-means/{means.pk}/",
            {"name": "PWNED"},
            format="json",
        )

        assert response.status_code == 405
        means.refresh_from_db()
        assert means.name == "Volunteering"

    def test_authenticated_user_cannot_delete_a_means(self, api_client, user_factory, means):
        api_client.force_authenticate(user=user_factory())

        response = api_client.delete(f"/workspaces/contribution-means/{means.pk}/")

        assert response.status_code == 405
        assert _means_model().objects.filter(pk=means.pk).exists()

    def test_authenticated_user_cannot_inject_a_means(self, api_client, user_factory, means):
        api_client.force_authenticate(user=user_factory())
        before = _means_model().objects.count()

        response = api_client.post("/workspaces/contribution-means/", {"name": "[QA] injected"}, format="json")

        assert response.status_code == 405
        assert _means_model().objects.count() == before

    def test_workspace_scoped_route_is_read_only_too(self, api_client, user_factory, workspace_factory, means):
        """The workspace-scoped subclass inherits the same action map and must
        not be the surviving write door.
        """
        workspace = workspace_factory()
        api_client.force_authenticate(user=user_factory())
        before = _means_model().objects.count()

        response = api_client.post(
            f"/workspaces/{workspace.id}/contribution-means/",
            {"name": "[QA] injected"},
            format="json",
        )

        assert response.status_code == 405
        assert _means_model().objects.count() == before


class TestContributionMeansReadsRequireAuth:
    def test_anonymous_list_is_refused(self, api_client, means):
        assert api_client.get("/workspaces/contribution-means/").status_code == 401

    def test_authenticated_list_still_works(self, api_client, user_factory, means):
        """The frontend's only use of this route (``listContributionMeans``)."""
        api_client.force_authenticate(user=user_factory())

        response = api_client.get("/workspaces/contribution-means/")

        assert response.status_code == 200

    def test_authenticated_detail_still_works(self, api_client, user_factory, means):
        api_client.force_authenticate(user=user_factory())

        response = api_client.get(f"/workspaces/contribution-means/{means.pk}/")

        assert response.status_code == 200
        assert response.data["name"] == "Volunteering"

    def test_workspace_scoped_list_still_works(self, api_client, user_factory, workspace_factory, means):
        workspace = workspace_factory()
        api_client.force_authenticate(user=user_factory())

        response = api_client.get(f"/workspaces/{workspace.id}/contribution-means/")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# WorkspaceCommentList — the un-scoped duplicate read + membership-free create
# ---------------------------------------------------------------------------


class TestWorkspaceCommentListSurface:
    def test_anonymous_list_is_refused(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        _comment_model().objects.create(workspace=workspace, author=user_factory(), comment="private")

        response = api_client.get("/workspaces/comment")

        assert response.status_code == 401

    def test_create_verb_is_gone(self, api_client, workspace_factory, user_factory):
        """POST here bypassed ``IsWorkspaceFollowerOrMember`` AND used the Get
        serializer, so it never set ``author``. The real create endpoint is
        ``/workspaces/comment/create/``.
        """
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)
        before = _comment_model().objects.count()

        response = api_client.post(
            "/workspaces/comment",
            {"workspace": str(workspace.id), "comment": "[QA] injected"},
            format="json",
        )

        assert response.status_code == 405
        assert _comment_model().objects.count() == before

    def test_list_is_scoped_to_the_callers_own_workspaces(self, api_client, workspace_factory, user_factory):
        mine = workspace_factory()
        theirs = workspace_factory()
        member = user_factory()
        _join(mine, member)
        visible = _comment_model().objects.create(workspace=mine, author=member, comment="mine")
        hidden = _comment_model().objects.create(workspace=theirs, author=user_factory(), comment="theirs")
        api_client.force_authenticate(user=member)

        response = api_client.get("/workspaces/comment")

        assert response.status_code == 200
        returned = {row["pk"] for row in response.data["results"]}
        assert visible.pk in returned
        assert hidden.pk not in returned

"""Authorization regression suite for the legacy ``/social/`` CRUD surface.

Context — the defect this locks shut
------------------------------------
``PostDetail`` (``RetrieveUpdateDestroyAPIView`` at ``/social/<int:pk>/``)
declared ``permission_classes = (RequiresFeatureFlag,)``. Because that
*replaces* the DRF project default (``IsAdminUser`` + ``IsAuthenticated``),
a feature flag was the ONLY gate on a read/update/**hard-delete** endpoint.

Three things compounded into an unauthenticated cross-tenant write:

1. ``RequiresFeatureFlag`` defines no ``has_object_permission``, so DRF's
   object-permission check passes by default.
2. ``resolve_workspace_id_from_request`` honours a caller-supplied
   ``?workspace_id=`` query param ABOVE the authenticated user's active
   workspace — so an anonymous caller picks which workspace the flag is
   evaluated against.
3. ``get_post_queryset()`` applies no owner/workspace/visibility filter, so
   ``get_object()`` resolves ANY post by integer pk.

Net effect, reproduced live against the local cluster on 2026-08-19:
``GET|PUT|PATCH|DELETE /social/<pk>/`` returned 401 unauthenticated, but
returned ``404 {"detail":"No Post matches the given query."}`` the moment
``?workspace_id=<a flag-enabled workspace>`` was appended — proving the whole
permission chain passed for an anonymous request and DRF reached object
lookup. Only a non-existent pk prevented the mutation.

The sibling ``CommentDetail`` already carried owner enforcement, which makes
``PostDetail`` a copy-paste omission rather than a deliberate policy.

The list/detail read surfaces (``PostList``, ``CommentList``,
``CommentDetail``) carried ``IsAuthenticatedOrReadOnly``, which permits
anonymous reads — and with the flag bypassed via ``?workspace_id=`` that
dumped every tenant's posts and comments to an anonymous caller (confirmed
live: 23 posts, 12 comments). These tests cover that surface too.

These tests must FAIL on the pre-fix controller.
"""

from __future__ import annotations

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
    set_workspace_flag,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.social.models import Post

pytestmark = pytest.mark.django_db

FLAG_KEY = "feature.social_feed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def post_factory(user_factory):
    """Create a Post owned by a given (or freshly made) author."""

    def _create(author=None, body="original body"):
        return Post.objects.create(author=author or user_factory(), body=body)

    return _create


def _seed_flag_enabled_workspace(workspace) -> None:
    """Turn ``feature.social_feed`` ON for exactly one workspace.

    Mirrors the live cluster's state: ``default_enabled=False`` globally with a
    single workspace-scoped rule enabled. This is the precondition an anonymous
    attacker points ``?workspace_id=`` at.
    """
    FeatureFlag.objects.update_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": False, "description": "authz regression seed"},
    )
    set_workspace_flag(FLAG_KEY, workspace.id, True, note="authz regression seed")


def _disable_flag_globally() -> None:
    flag, _ = FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": False, "description": "authz regression seed"},
    )
    FeatureFlagRule.objects.update_or_create(
        flag=flag,
        scope=FeatureFlagRule.Scope.GLOBAL,
        defaults={"enabled": False, "note": "authz regression seed"},
    )
    bump_feature_flags_version()


DENIED = {401, 403}


def _call(api_client, method: str, url: str, *, author_id=None):
    """Issue ``method`` at ``url``, sending a body only for the write verbs.

    Django's test client REPLACES a URL's query string with the ``data`` dict on
    GET/DELETE, which would silently strip the ``?workspace_id=`` that is the
    whole point of these tests (and turn a real hole into a false pass).
    """
    if method in ("put", "patch"):
        payload = {"body": "pwned"}
        if method == "put":
            payload["author"] = str(author_id)
        return getattr(api_client, method)(url, payload, format="json")
    return getattr(api_client, method)(url)


# ---------------------------------------------------------------------------
# 1. The live exploit — anonymous + ?workspace_id= pointed at an enabled
#    workspace must NOT reach the object.
# ---------------------------------------------------------------------------


@pytest.mark.real_feature_flags
@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_anonymous_denied_even_with_flag_enabled_workspace_param(api_client, workspace_factory, post_factory, method):
    """The reproduction. Flag evaluates TRUE via the query param; auth must still deny."""
    workspace = workspace_factory()
    _seed_flag_enabled_workspace(workspace)
    post = post_factory(body="victim body")
    api_client.raise_request_exception = False

    url = f"/social/{post.pk}/?workspace_id={workspace.id}"
    response = _call(api_client, method, url, author_id=post.author_id)

    assert response.status_code in DENIED, (
        f"anonymous {method.upper()} /social/<pk>/?workspace_id=<enabled ws> must be denied, got {response.status_code}"
    )
    post.refresh_from_db()
    assert post.body == "victim body"


@pytest.mark.real_feature_flags
def test_anonymous_delete_with_workspace_param_does_not_destroy_post(api_client, workspace_factory, post_factory):
    """DELETE on this view is a HARD delete — assert the row survives."""
    workspace = workspace_factory()
    _seed_flag_enabled_workspace(workspace)
    post = post_factory()
    api_client.raise_request_exception = False

    api_client.delete(f"/social/{post.pk}/?workspace_id={workspace.id}")

    assert Post.objects.filter(pk=post.pk).exists(), "anonymous DELETE hard-deleted another user's post"


@pytest.mark.real_feature_flags
@pytest.mark.parametrize("param", ["workspace_id", "workspace"])
def test_anonymous_denied_for_both_workspace_param_aliases(api_client, workspace_factory, post_factory, param):
    """``resolve_workspace_id_from_request`` honours ``workspace_id`` AND ``workspace``."""
    workspace = workspace_factory()
    _seed_flag_enabled_workspace(workspace)
    post = post_factory()
    api_client.raise_request_exception = False

    response = api_client.patch(f"/social/{post.pk}/?{param}={workspace.id}", {"body": "pwned"}, format="json")

    assert response.status_code in DENIED


# ---------------------------------------------------------------------------
# 2. Anonymous access denied regardless of how the flag resolves.
#    (Default test fixture forces every flag ON — the strongest precondition.)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_anonymous_denied_on_post_detail(api_client, post_factory, method):
    post = post_factory(body="victim body")
    api_client.raise_request_exception = False

    response = _call(api_client, method, f"/social/{post.pk}/", author_id=post.author_id)

    assert response.status_code in DENIED, f"{method.upper()} leaked to anonymous"
    post.refresh_from_db()
    assert post.body == "victim body"


@pytest.mark.parametrize(
    "url_template",
    ["/social/", "/social/comment", "/social/{pk}/"],
)
def test_anonymous_cannot_read_legacy_social_surface(api_client, post_factory, url_template):
    """The legacy CRUD surface is workspace-unscoped — anonymous reads dumped every tenant."""
    post = post_factory()
    api_client.raise_request_exception = False

    response = api_client.get(url_template.format(pk=post.pk))

    assert response.status_code in DENIED, (
        f"anonymous GET {url_template} exposed workspace-unscoped social content (got {response.status_code})"
    )


def test_post_list_is_tenant_scoped_for_authenticated_callers(api_client, user_factory, post_factory):
    """Authentication alone is not enough — ``/social/`` must not list foreign posts.

    ``PostList`` now shares ``get_posts_visible_to`` with ``PostDetail`` rather
    than serving ``get_post_queryset()`` (every post on the deployment). autosec
    is single-DB, so this filter IS the tenant boundary (ADR 0028).
    """
    stranger_post = post_factory(body="another tenant's post")
    caller = user_factory()
    own_post = post_factory(author=caller, body="my post")
    api_client.force_authenticate(user=caller)

    response = api_client.get("/social/")

    assert response.status_code == 200, response.data
    returned = {row["id"] for row in response.data["results"]}
    assert own_post.pk in returned, "the caller's own post must remain visible"
    assert stranger_post.pk not in returned, "/social/ listed a post from a workspace the caller has no membership in"


# ---------------------------------------------------------------------------
# 3. Authenticated non-owner cannot mutate someone else's post.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_authenticated_non_owner_cannot_mutate_post(api_client, user_factory, post_factory, method):
    """A signed-in stranger must not touch someone else's post.

    Either denial code is correct, and which one fires depends on how far the
    request gets: ``IsOwnerOrReadOnly`` answers 403 when the object is inside the
    caller's visible queryset (e.g. a fellow workspace member), while
    ``get_posts_visible_to`` answers 404 when it is not — the stronger outcome,
    because it is not an existence oracle. What must never vary is the effect on
    the row, which is asserted below.
    """
    owner = user_factory()
    post = post_factory(author=owner, body="owner body")
    attacker = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=attacker)

    response = _call(api_client, method, f"/social/{post.pk}/", author_id=owner.id)

    assert response.status_code in (403, 404), (
        f"non-owner {method.upper()} should be denied, got {response.status_code}"
    )
    assert Post.objects.filter(pk=post.pk).exists(), f"non-owner {method.upper()} destroyed the row"
    post.refresh_from_db()
    assert post.body == "owner body", f"non-owner {method.upper()} rewrote the body"


# ---------------------------------------------------------------------------
# 4. The owner must still be able to work — do not break the working surface.
# ---------------------------------------------------------------------------


def test_owner_can_read_own_post(api_client, user_factory, post_factory):
    owner = user_factory()
    post = post_factory(author=owner)
    api_client.force_authenticate(user=owner)

    response = api_client.get(f"/social/{post.pk}/")

    assert response.status_code == 200


def test_owner_can_patch_own_post(api_client, user_factory, post_factory):
    owner = user_factory()
    post = post_factory(author=owner, body="before")
    api_client.force_authenticate(user=owner)

    response = api_client.patch(f"/social/{post.pk}/", {"body": "after"}, format="json")

    assert response.status_code == 200, response.data
    post.refresh_from_db()
    assert post.body == "after"


def test_owner_can_delete_own_post(api_client, user_factory, post_factory):
    owner = user_factory()
    post = post_factory(author=owner)
    api_client.force_authenticate(user=owner)

    response = api_client.delete(f"/social/{post.pk}/")

    assert response.status_code == 204
    assert not Post.objects.filter(pk=post.pk).exists()


# ---------------------------------------------------------------------------
# 5. The feature flag must still gate the FEATURE (additive to auth, not
#    a substitute for it).
# ---------------------------------------------------------------------------


@pytest.mark.real_feature_flags
@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_flag_off_still_blocks_the_owner(api_client, user_factory, post_factory, method):
    _disable_flag_globally()
    owner = user_factory()
    post = post_factory(author=owner)
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=owner)

    response = _call(api_client, method, f"/social/{post.pk}/", author_id=owner.id)

    assert response.status_code == 403, (
        f"{method.upper()} should 403 when feature.social_feed is off, got {response.status_code}"
    )

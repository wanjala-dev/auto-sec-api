"""Tenant isolation for the feed INTERACTION surface (`/social/posts/<pk>/…`).

autosec's pooled tier is one shared database scoped by ``workspace_id``
(ADR 0028), so the application-level filter IS the tenant boundary — there is
no database boundary behind it to catch a missing predicate.

These three seams had no such filter. They resolved a post by integer ``pk``
alone, so any authenticated user — with no membership anywhere near the target
workspace — could walk sequential pks to:

* read another tenant's comments   (`GET  /social/posts/<pk>/comments/`)
* write a comment onto their post  (`POST /social/posts/<pk>/comments/`)
* like their post                  (`POST /social/posts/<pk>/like/`)

Reproduced live on 2026-08-20 (all three returned 200) before the fix. Retiring
the legacy `/social/` CRUD removed two readers of the same unscoped pattern but
left these, which are the ones the HUD actually calls.

Every denial asserts **404, not 403**: a 403 confirms the row exists and turns
the endpoint into a cross-tenant existence oracle (tenancy skill §6).
"""

from __future__ import annotations

import pytest

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag
from infrastructure.persistence.social.models import Comment, Post
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]


@pytest.fixture(autouse=True)
def _social_feed_flag_on():
    """These routes sit behind feature.social_feed; isolate authz, not the gate."""
    FeatureFlag.objects.update_or_create(
        key="feature.social_feed",
        defaults={"default_enabled": True, "description": "tenant isolation test"},
    )
    bump_feature_flags_version()


def _member(workspace, user):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.ACTIVE,
    )


@pytest.fixture
def tenant_a(user_factory, workspace_factory):
    """A workspace with a post and a comment, owned by someone else entirely."""
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    post = Post.objects.create(author=owner, body="tenant A body", workspace=workspace)
    comment = Comment.objects.create(post=post, author=owner, comment="tenant A comment")
    return {"owner": owner, "workspace": workspace, "post": post, "comment": comment}


@pytest.fixture
def outsider(api_client, user_factory):
    """Authenticated, but holds no membership in tenant A."""
    user = user_factory()
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user)
    return user


# ---------------------------------------------------------------------------
# Cross-tenant reads
# ---------------------------------------------------------------------------


def test_outsider_cannot_read_another_tenants_comments(api_client, tenant_a, outsider):
    """The reproduced leak: this returned 200 with tenant A's comment body."""
    response = api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/")

    assert response.status_code == 404, (
        f"cross-tenant comment read returned {response.status_code}; payload={getattr(response, 'data', None)}"
    )


def test_denial_is_404_not_403_so_existence_is_not_disclosed(api_client, tenant_a, outsider):
    """A real post and an absent one must be indistinguishable to an outsider."""
    real = api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/")
    absent = api_client.get("/social/posts/99999999/comments/")

    assert real.status_code == absent.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant writes
# ---------------------------------------------------------------------------


def test_outsider_cannot_comment_on_another_tenants_post(api_client, tenant_a, outsider):
    before = Comment.objects.filter(post=tenant_a["post"]).count()

    response = api_client.post(
        f"/social/posts/{tenant_a['post'].pk}/comments/",
        {"comment": "injected by an outsider"},
        format="json",
    )

    assert response.status_code == 404
    assert Comment.objects.filter(post=tenant_a["post"]).count() == before, (
        "an outsider's comment was persisted onto another tenant's post"
    )


def test_outsider_cannot_like_another_tenants_post(api_client, tenant_a, outsider):
    response = api_client.post(f"/social/posts/{tenant_a['post'].pk}/like/", {}, format="json")

    assert response.status_code == 404
    assert tenant_a["post"].likes.count() == 0, "an outsider's like landed on another tenant's post"


def test_anonymous_callers_are_rejected(api_client, tenant_a):
    """No credentials at all — the permission layer answers before scoping."""
    api_client.raise_request_exception = False

    assert api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/").status_code in (401, 403)
    assert api_client.post(f"/social/posts/{tenant_a['post'].pk}/like/", {}, format="json").status_code in (401, 403)


# ---------------------------------------------------------------------------
# The legitimate paths must still work — a scope that denies everyone is not a fix
# ---------------------------------------------------------------------------


def test_workspace_member_can_read_and_write(api_client, tenant_a, user_factory):
    member = user_factory()
    _member(tenant_a["workspace"], member)
    api_client.force_authenticate(user=member)

    listed = api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/")
    assert listed.status_code == 200
    assert len(listed.data["data"]) == 1

    commented = api_client.post(
        f"/social/posts/{tenant_a['post'].pk}/comments/",
        {"comment": "a legitimate member comment"},
        format="json",
    )
    assert commented.status_code == 201

    liked = api_client.post(f"/social/posts/{tenant_a['post'].pk}/like/", {}, format="json")
    assert liked.status_code == 200
    assert liked.data["data"]["liked"] is True


def test_workspace_owner_can_read(api_client, tenant_a):
    api_client.force_authenticate(user=tenant_a["owner"])

    response = api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/")

    assert response.status_code == 200
    assert len(response.data["data"]) == 1


def test_author_of_a_workspaceless_post_keeps_access(api_client, user_factory):
    """The author leg is load-bearing: pre-feed posts have workspace = NULL.

    Without it they become unreachable to the person who wrote them.
    """
    author = user_factory()
    post = Post.objects.create(author=author, body="legacy, no workspace", workspace=None)
    Comment.objects.create(post=post, author=author, comment="legacy comment")
    api_client.force_authenticate(user=author)

    response = api_client.get(f"/social/posts/{post.pk}/comments/")

    assert response.status_code == 200
    assert len(response.data["data"]) == 1


def test_soft_deleted_post_is_not_reachable(api_client, tenant_a):
    """Scoping must not accidentally resurrect soft-deleted posts."""
    tenant_a["post"].is_deleted = True
    tenant_a["post"].save(update_fields=["is_deleted"])
    api_client.force_authenticate(user=tenant_a["owner"])

    assert api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/").status_code == 404


@pytest.mark.parametrize(
    "status_value",
    [WorkspaceMembership.Status.INVITED, WorkspaceMembership.Status.SUSPENDED],
)
def test_non_active_membership_does_not_grant_access(api_client, tenant_a, user_factory, status_value):
    """Only ACTIVE membership counts — an invited or suspended row must not.

    A merely-invited user has not accepted, and a suspended one has had access
    taken away; either reading the workspace's posts would defeat the point.
    """
    lapsed = user_factory()
    WorkspaceMembership.objects.create(
        workspace=tenant_a["workspace"],
        user=lapsed,
        role=WorkspaceMembership.Role.MEMBER,
        status=status_value,
    )
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=lapsed)

    assert api_client.get(f"/social/posts/{tenant_a['post'].pk}/comments/").status_code == 404

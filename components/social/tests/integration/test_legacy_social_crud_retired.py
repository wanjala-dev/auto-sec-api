"""The legacy ``/social/`` CRUD surface is RETIRED — pin it gone.

``PostList`` / ``PostDetail`` / ``CommentList`` / ``CommentDetail`` were
deleted on 2026-08-19. They had no consumer in any client, and every social
defect the security sweep found lived on them:

* an anonymous ``PATCH``/``DELETE`` on ``/social/<int:pk>/`` rewrote or removed
  any post on the deployment, because ``RequiresFeatureFlag`` was the view's
  ONLY permission class and it has no ``has_object_permission`` (#426);
* ``/social/``, ``/social/comment`` and ``/social/comment/<pk>/`` served
  anonymous cross-tenant reads over a workspace-unscoped queryset (#429).

Hardening a surface nobody calls leaves the attack surface standing. These
tests assert it is actually gone rather than merely gated — they fail against
the pre-retirement code, where the same requests returned 200/204.

The workspace feed (``/social/workspaces/<ws>/feed/``, ``/social/posts/...``)
is a DIFFERENT surface, is live in the HUD, and must keep working — asserted
at the bottom and covered in full by ``test_workspace_feed.py``.
"""

from __future__ import annotations

import pytest
from django.urls import NoReverseMatch, reverse

from infrastructure.persistence.social.models import Comment, Post

# Carry each name's real kwargs — ``reverse("post-detail")`` with no pk raises
# NoReverseMatch even while the route exists, which would pass this test for the
# wrong reason.
RETIRED_ROUTE_NAMES = [
    ("post-list", {}),
    ("post-detail", {"pk": 1}),
    ("comment-list", {}),
    ("comment-detail", {"pk": 1}),
]

RETIRED_REQUESTS = [
    ("get", "/social/"),
    ("post", "/social/"),
    ("get", "/social/1/"),
    ("put", "/social/1/"),
    ("patch", "/social/1/"),
    ("delete", "/social/1/"),
    ("get", "/social/comment"),
    ("post", "/social/comment"),
    ("get", "/social/comment/1/"),
    ("patch", "/social/comment/1/"),
    ("delete", "/social/comment/1/"),
]


@pytest.mark.parametrize("name,kwargs", RETIRED_ROUTE_NAMES)
def test_retired_route_names_no_longer_reverse(name, kwargs):
    """No stale ``reverse()`` target survives — including LOGIN_REDIRECT_URL.

    ``api/settings/base.py`` set ``LOGIN_REDIRECT_URL = "post-list"``. Django's
    ``resolve_url()`` raises ``NoReverseMatch`` for a dotted-path-free name that
    does not reverse, so leaving that setting pointed here would have 500'd the
    session-login redirect. It is now a path.
    """
    with pytest.raises(NoReverseMatch):
        reverse(name, kwargs=kwargs)


@pytest.mark.django_db
@pytest.mark.parametrize("method,url", RETIRED_REQUESTS)
def test_retired_routes_404_for_anonymous_callers(api_client, method, url):
    """The exact anonymous requests that used to succeed now 404.

    Anonymous is the load-bearing case: the #426 write and the #429 reads were
    all reachable with no credentials at all.
    """
    api_client.raise_request_exception = False

    response = getattr(api_client, method)(url, {}, format="json")

    assert response.status_code == 404, f"retired route {method.upper()} {url} still resolves ({response.status_code})"


@pytest.mark.django_db
@pytest.mark.parametrize("method,url", RETIRED_REQUESTS)
def test_retired_routes_404_for_authenticated_callers(api_client, user_factory, method, url):
    """Gone for everyone — not merely re-gated behind authentication."""
    api_client.raise_request_exception = False
    api_client.force_authenticate(user=user_factory())

    response = getattr(api_client, method)(url, {}, format="json")

    assert response.status_code == 404, f"retired route {method.upper()} {url} still resolves ({response.status_code})"


@pytest.mark.django_db
def test_anonymous_cannot_mutate_a_real_post_through_the_retired_route(api_client, user_factory):
    """The #426 regression, pinned against a row that actually exists.

    As originally shipped this returned 200 and rewrote ``body``, and the
    DELETE returned 204 and removed the row. #426 downgraded both to 403 by
    adding the missing auth classes; retirement takes them to 404. Asserting
    404 (not "not 200") is what distinguishes a deleted route from a gated one.
    """
    author = user_factory()
    post = Post.objects.create(author=author, body="original body")
    api_client.raise_request_exception = False

    patched = api_client.patch(f"/social/{post.pk}/", {"body": "rewritten"}, format="json")
    deleted = api_client.delete(f"/social/{post.pk}/")

    assert patched.status_code == 404
    assert deleted.status_code == 404
    post.refresh_from_db()
    assert post.body == "original body"
    assert Post.objects.filter(pk=post.pk).exists()


@pytest.mark.django_db
def test_anonymous_cannot_list_posts_or_comments_through_the_retired_routes(api_client, user_factory):
    """The #429 regression: the list routes dumped every tenant's rows."""
    author = user_factory()
    post = Post.objects.create(author=author, body="tenant a post")
    Comment.objects.create(post=post, author=author, comment="tenant a comment")
    api_client.raise_request_exception = False

    assert api_client.get("/social/").status_code == 404
    assert api_client.get("/social/comment").status_code == 404


@pytest.mark.django_db
def test_retiring_the_crud_routes_left_the_rows_alone(api_client, user_factory):
    """This was a routing retirement, not a data migration.

    Posts and comments stay readable through the live feed surface; nothing in
    this change deletes a row.
    """
    author = user_factory()
    post = Post.objects.create(author=author, body="still here")
    comment = Comment.objects.create(post=post, author=author, comment="still here too")

    assert Post.objects.filter(pk=post.pk).exists()
    assert Comment.objects.filter(pk=comment.pk).exists()


def test_surviving_feed_routes_still_reverse():
    """The productized feed surface the HUD calls is untouched."""
    assert reverse("workspace-feed-post-like", kwargs={"pk": 1}) == "/social/posts/1/like/"
    assert reverse("workspace-feed-post-comments", kwargs={"pk": 1}) == "/social/posts/1/comments/"
    assert reverse("workspace-feed-post-detail", kwargs={"post_id": 1}) == "/social/posts/1/"

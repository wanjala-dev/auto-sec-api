"""Social bounded context controller.

HTTP endpoints for the WORKSPACE FEED — the per-workspace, follow-filtered
operator feed the HUD renders (``?panel=social``). This is the single driving
adapter — business logic belongs in application use-cases, not here.

Retired 2026-08-19 — the legacy generic CRUD surface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``PostList`` / ``PostDetail`` / ``CommentList`` / ``CommentDetail`` (mounted at
``/social/``, ``/social/<int:pk>/``, ``/social/comment``,
``/social/comment/<int:pk>/``) were DELETED, along with the never-routed
follower / like / dislike / reply views that shared their serializers.

They were retired rather than hardened because every social defect found in the
security sweep lived on them and nothing consumed them:

* ``PostDetail`` carried ``permission_classes = (RequiresFeatureFlag,)`` as its
  only gate, which REPLACES the project default. ``RequiresFeatureFlag`` only
  answers "is the flag on" and has no ``has_object_permission``, so an
  anonymous ``PATCH``/``DELETE`` by integer pk rewrote or removed any post. The
  flag was not a gate either — ``resolve_workspace_id_from_request`` honours a
  caller-supplied ``?workspace_id=`` BEFORE authentication, letting the caller
  pick a flag-enabled workspace. (#426)
* ``PostList`` / ``CommentList`` / ``CommentDetail`` served anonymous
  cross-tenant reads over a workspace-unscoped queryset. (#429)

The #429 fix escalated the untenanted COMMENT queryset rather than fixing it,
because no comment carries a workspace. Deleting the only two views that read
it settles that: the feed's comment routes below are addressed per-post, and
``list_post_comments`` is reachable only through a post the caller resolved.

The productized feed surface below is unaffected and stays: it is the only
social surface any client calls.
"""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.shared_platform.api.permissions import RequiresFeatureFlag
from components.social.api.requests.create_feed_post_request import (
    CreateFeedPostRequest,
)
from components.social.api.resources.feed_post_resource import (
    FeedPageResource,
    FeedPostResource,
)
from components.social.application.commands.create_workspace_post_command import (
    CreateWorkspacePostCommand,
)
from components.social.application.providers.feed_provider import FeedProvider
from components.social.application.queries.list_workspace_feed_query import (
    ListWorkspaceFeedQuery,
)
from components.social.application.service import SocialService
from components.social.application.use_cases.create_workspace_post_use_case import (
    PostAuthorizationError as CreatePostAuthorizationError,
)
from components.social.application.use_cases.delete_post_use_case import (
    PostAuthorizationError as DeletePostAuthorizationError,
)
from components.social.application.use_cases.delete_post_use_case import (
    PostNotFoundError as DeletePostNotFoundError,
)
from components.social.application.use_cases.edit_post_use_case import (
    PostAuthorizationError as EditPostAuthorizationError,
)
from components.social.application.use_cases.edit_post_use_case import (
    PostNotFoundError as EditPostNotFoundError,
)
from components.social.application.use_cases.list_workspace_feed_use_case import (
    FeedAuthorizationError,
)

# The social feed is gated behind feature.social_feed per the GTM scope freeze.
# Workspace-internal updates live in other bounded contexts and are unaffected.
_SOCIAL_FEED_FLAG_KEY = "feature.social_feed"

_social_service = SocialService()


def _enrich_post_authors(posts: list[dict]) -> None:
    """Inject ``author_name`` into serialized feed posts.

    The FeedPostResource carries only ``author_id`` (the domain entity stays
    user-detail-free). This is a presentation concern; the display names are
    batch-resolved through ``SocialService`` in ONE query (no N+1) and the
    dicts are mutated in place. Posts with an unresolved author fall back to
    ``None``.
    """
    if not posts:
        return
    author_ids = {p.get("author_id") for p in posts if p.get("author_id")}
    if not author_ids:
        return
    names = _social_service.resolve_user_display_names(author_ids)
    for post in posts:
        post["author_name"] = names.get(str(post.get("author_id")))


# ── Workspace feed (follow-filtered, per-workspace broadcast) ───────────


class WorkspaceFeedView(APIView):
    """List or create posts in a workspace's feed.

    ``GET /workspaces/<id>/feed/`` returns posts from members the caller
    follows (plus their own). ``POST`` creates a new post. Supports an
    optional ``team_id`` query param to scope to a single team feed.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "workspace-feed"

    def get(self, request, workspace_id):
        team_id_raw = request.query_params.get("team_id")
        cursor = request.query_params.get("cursor")
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
        except (TypeError, ValueError):
            limit = 20
        try:
            team_id = int(team_id_raw) if team_id_raw else None
        except ValueError:
            return Response(
                {"success": False, "error": "team_id must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        query = ListWorkspaceFeedQuery(
            viewer_id=request.user.id,
            workspace_id=workspace_id,
            team_id=team_id,
            cursor=cursor,
            limit=limit,
        )
        try:
            page = FeedProvider.list_feed_use_case().execute(query)
        except FeedAuthorizationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = FeedPageResource.from_page(page).to_dict()
        posts = data.get("posts") or []
        _enrich_post_authors(posts)
        self._enrich_viewer_likes(posts, request.user)
        return Response({"success": True, "data": data})

    @staticmethod
    def _enrich_viewer_likes(posts, viewer) -> None:
        """Flag which posts the viewer has liked (one query for the page)."""
        if not posts:
            return
        liked_ids = _social_service.viewer_liked_post_ids([p["id"] for p in posts], viewer)
        for post in posts:
            post["liked"] = post["id"] in liked_ids

    def post(self, request, workspace_id):
        req = CreateFeedPostRequest.from_payload(request.data)
        if not req.body:
            return Response(
                {"success": False, "error": "Post body is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        command = CreateWorkspacePostCommand.build(
            author_id=request.user.id,
            workspace_id=workspace_id,
            body=req.body,
            team_id=req.team_id,
            visibility=req.visibility,
            image_ids=req.image_ids,
        )
        try:
            post = FeedProvider.create_post_use_case().execute(command)
        except CreatePostAuthorizationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created = FeedPostResource.from_entity(post).to_dict()
        _enrich_post_authors([created])
        return Response(
            {"success": True, "data": created},
            status=status.HTTP_201_CREATED,
        )


class WorkspaceFeedPostDetail(APIView):
    """PATCH (edit body) or DELETE (soft-delete) a single feed post."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "workspace-feed-post-detail"

    def patch(self, request, post_id):
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response(
                {"success": False, "error": "Post body is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            post = FeedProvider.edit_post_use_case().execute(post_id=post_id, actor_id=request.user.id, body=body)
        except EditPostNotFoundError:
            return Response(
                {"success": False, "error": "Post not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except EditPostAuthorizationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        detail = FeedPostResource.from_entity(post).to_dict()
        _enrich_post_authors([detail])
        return Response({"success": True, "data": detail})

    def delete(self, request, post_id):
        try:
            FeedProvider.delete_post_use_case().execute(post_id=post_id, actor_id=request.user.id)
        except DeletePostNotFoundError:
            return Response(
                {"success": False, "error": "Post not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except DeletePostAuthorizationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Feed post interactions: like toggle + comments ──────────────────────


class WorkspaceFeedPostLikeView(APIView):
    """Toggle the caller's like on a feed post.

    ``POST /social/posts/<pk>/like/`` → flips membership in ``Post.likes`` and
    returns the new ``{liked, like_count}``. Idempotent per toggle.
    """

    permission_classes = (permissions.IsAuthenticated, RequiresFeatureFlag)
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY
    name = "workspace-feed-post-like"

    def post(self, request, pk):
        result = _social_service.toggle_feed_post_like(pk, request.user)
        if result is None:
            return Response(
                {"success": False, "error": "Post not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        liked, like_count = result
        return Response({"success": True, "data": {"liked": liked, "like_count": like_count}})


class WorkspaceFeedPostCommentsView(APIView):
    """List or add comments on a feed post.

    ``GET  /social/posts/<pk>/comments/`` → newest-first comments.
    ``POST /social/posts/<pk>/comments/`` → add a comment (body: ``{comment}``).
    """

    permission_classes = (permissions.IsAuthenticated, RequiresFeatureFlag)
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY
    name = "workspace-feed-post-comments"

    @staticmethod
    def _serialize(comment) -> dict:
        author = comment.author
        name = f"{author.first_name or ''} {author.last_name or ''}".strip()
        return {
            "id": comment.id,
            "comment": comment.comment,
            "author_id": str(author.id),
            "author_name": name or author.username or author.email,
            "created_on": comment.created_on.isoformat() if comment.created_on else "",
        }

    def get(self, request, pk):
        if not _social_service.post_exists(pk):
            return Response(
                {"success": False, "error": "Post not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        comments = _social_service.list_post_comments(pk, limit=100)
        return Response({"success": True, "data": [self._serialize(c) for c in comments]})

    def post(self, request, pk):
        body = (request.data.get("comment") or request.data.get("body") or "").strip()
        if not body:
            return Response(
                {"success": False, "error": "Comment body is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        comment = _social_service.add_post_comment(post_id=pk, author=request.user, body=body)
        if comment is None:
            return Response(
                {"success": False, "error": "Post not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {"success": True, "data": self._serialize(comment)},
            status=status.HTTP_201_CREATED,
        )

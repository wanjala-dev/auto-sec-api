"""Social bounded context controller.

HTTP endpoints for the social feed: posts, comments, tags,
followers, likes/dislikes.  This is the single driving adapter —
business logic belongs in application use-cases, not here.

NOTE: Messaging (threads, messages, inbox) has been extracted to
``components.messaging``.  See ``/messaging/`` endpoints.
"""

from __future__ import annotations

from rest_framework import generics, permissions, status
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from components.identity.application.facades.serializer_facade import UserSerializer
from components.notifications.application.facades.notification_facade import (
    NotificationDispatcher,
)
from components.shared_platform.api.permissions import RequiresFeatureFlag
from components.social.api.permissions import IsOwnerOrReadOnly
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

# The standalone social product (posts, comments, tags at /social/) is gated
# behind feature.social_feed per the GTM scope freeze. Workspace-internal
# updates live in other bounded contexts and are unaffected.
_SOCIAL_FEED_FLAG_KEY = "feature.social_feed"
from components.notifications.application.providers.notifications_models_provider import (
    get_notifications_models_provider,
)
from components.shared_platform.mappers.rest.core_serializers import EmptySerializer
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
from components.social.mappers.rest.social_serializers import (
    CommentSerializer,
    PostSerializer,
    TagSerializer,
)
from components.workspace.api.workspace_permissions import (
    IsUnauthenticatedOrAdminOrStaff,
)

notification_dispatcher = NotificationDispatcher()
_social_service = SocialService()
Notification = get_notifications_models_provider().Notification


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


# ── Followers ───────────────────────────────────────────────────────────


class AddFollower(generics.ListCreateAPIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = EmptySerializer

    def post(self, request, pk=None, *args, **kwargs):
        user_id = pk
        profile = _social_service.add_follower(user_id, request.user.id)
        notification_dispatcher.dispatch(
            actor=request.user,
            workspace=getattr(profile, "workspace", None),
            verb="started following you",
            notification_type=Notification.NotificationType.FOLLOW,
            recipients=[profile.user],
            target=profile,
        )
        return Response({"success": True, "message": "User followed Successfully"}, status=status.HTTP_200_OK)


class RemoveFollower(generics.ListCreateAPIView):
    serializer_class = EmptySerializer

    def post(self, request, pk, *args, **kwargs):
        user_id = pk
        _social_service.remove_follower(user_id, request.user.id)
        return Response({"success": True, "message": "User unfollowed Successfully"}, status=status.HTTP_200_OK)


class ListFollowers(RetrieveAPIView):
    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserSerializer

    def get(self, request, pk, *args, **kwargs):
        user_id = pk
        followers = _social_service.get_followers(user_id)
        serializer = UserSerializer(instance=followers, many=True, context={"request": request})
        return Response({"data": serializer.data}, status=status.HTTP_200_OK)


# ── Posts ────────────────────────────────────────────────────────────────


class PostList(generics.ListCreateAPIView):
    serializer_class = PostSerializer
    name = "post-list"
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
        RequiresFeatureFlag,
    )
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY
    filter_fields = (
        "shared_body",
        "body",
        "created_on",
        "shared_on",
        "author",
        "shared_user",
        "likes",
        "dislikes",
        "tags",
    )
    search_fields = ("^body",)
    ordering_fields = ("id", "created_on")

    def get_queryset(self):
        return _social_service.get_post_queryset()


class PostDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PostSerializer
    name = "post-detail"
    permission_classes = (RequiresFeatureFlag,)
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY

    def get_queryset(self):
        return _social_service.get_post_queryset()


class ListPosts(RetrieveAPIView):
    """List posts from users the authenticated user follows."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = PostSerializer

    def get(self, request, *args, **kwargs):
        posts = _social_service.get_followed_posts(request.user.id)
        serializer = PostSerializer(instance=posts, many=True, context={"request": request})
        return Response({"data": serializer.data}, status=status.HTTP_200_OK)


# ── Likes / Dislikes ────────────────────────────────────────────────────


class AddLike(generics.ListCreateAPIView):
    serializer_class = EmptySerializer

    def post(self, request, pk, *args, **kwargs):
        post, liked = _social_service.toggle_post_like(pk, request.user)
        if liked:
            notification_dispatcher.dispatch(
                actor=request.user,
                workspace=getattr(post, "workspace", None),
                verb="liked your post",
                notification_type=Notification.NotificationType.LIKE,
                recipients=[post.author],
                target=post,
            )
        return Response(
            {
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "success",
            }
        )


class AddDislike(generics.ListCreateAPIView):
    serializer_class = EmptySerializer

    def post(self, request, pk, *args, **kwargs):
        _social_service.toggle_post_dislike(pk, request.user)
        return Response(
            {
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "success",
            }
        )


# ── Comments ────────────────────────────────────────────────────────────


class CommentList(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    name = "comment-list"
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
        RequiresFeatureFlag,
    )
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY
    filter_fields = (
        "id",
        "comment",
        "created_on",
        "author",
        "post",
        "likes",
        "dislikes",
        "parent",
    )
    search_fields = ("^comment",)
    ordering_fields = ("id", "created_on")

    def get_queryset(self):
        return _social_service.get_comment_queryset()


class CommentDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CommentSerializer
    name = "comment-detail"
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
        RequiresFeatureFlag,
    )
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY

    def get_queryset(self):
        return _social_service.get_comment_queryset()


class SocialCommentReplyView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer

    def post(self, request, post_pk, pk, *args, **kwargs):
        data = request.data
        serializer = CommentSerializer(data=data)
        new_comment, post, parent_comment = _social_service.create_reply(
            author=request.user,
            post_id=post_pk,
            parent_comment_id=pk,
        )

        notification_dispatcher.dispatch(
            actor=request.user,
            workspace=getattr(post, "workspace", None),
            verb="replied to your comment",
            notification_type=Notification.NotificationType.COMMENT,
            recipients=[parent_comment.author],
            target=new_comment,
        )

        if serializer.is_valid():
            serializer.save()
            return Response({"msg": "Replied"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AddCommentLike(generics.ListCreateAPIView):
    serializer_class = EmptySerializer

    def post(self, request, pk, *args, **kwargs):
        comment, liked = _social_service.toggle_comment_like(pk, request.user)
        if liked:
            notification_dispatcher.dispatch(
                actor=request.user,
                workspace=getattr(comment, "workspace", None),
                verb="liked your comment",
                notification_type=Notification.NotificationType.LIKE,
                recipients=[comment.author],
                target=comment,
            )
        return Response(
            {
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "success",
            }
        )


class AddCommentDislike(generics.ListCreateAPIView):
    serializer_class = EmptySerializer

    def post(self, request, pk, *args, **kwargs):
        _social_service.toggle_comment_dislike(pk, request.user)
        return Response(
            {
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "success",
            }
        )


# ── Tags ─────────────────────────────────────────────────────────────────


class SocialTagList(generics.ListCreateAPIView):
    serializer_class = TagSerializer
    name = "tag-list"
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
        RequiresFeatureFlag,
    )
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY
    filter_fields = ("id", "name")
    search_fields = ("^name",)
    ordering_fields = ("id",)

    def get_queryset(self):
        return _social_service.get_tag_queryset()


class TagDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TagSerializer
    name = "tag-detail"
    permission_classes = (
        permissions.IsAuthenticatedOrReadOnly,
        IsOwnerOrReadOnly,
        RequiresFeatureFlag,
    )
    feature_flag_key = _SOCIAL_FEED_FLAG_KEY

    def get_queryset(self):
        return _social_service.get_tag_queryset()


# NOTE: Thread/Message/Inbox endpoints have been extracted to
# ``components.messaging``.  See ``/messaging/`` URL namespace.


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

"""ORM repository for the social bounded context.

Backs the workspace-feed interaction surface only (likes + per-post comments +
author-name resolution). The unscoped post/comment querysets, the follower
methods and the dislike toggle were deleted with the legacy ``/social/`` CRUD
views that were their only callers (retired 2026-08-19 — see
``components/social/api/controller.py``).

Feed reads/writes do NOT come through here: they go through
``feed_post_repository.FeedPostRepository``, which implements ``PostStorePort``
and scopes every query to a workspace.
"""

from __future__ import annotations


class SocialRepository:
    """Encapsulates ORM access for the workspace-feed interaction surface."""

    # ── Feed posts ───────────────────────────────────────────────────────

    def get_active_post(self, post_id):
        from infrastructure.persistence.social.models import Post

        return Post.objects.filter(pk=post_id, is_deleted=False).first()

    def post_exists(self, post_id) -> bool:
        from infrastructure.persistence.social.models import Post

        return Post.objects.filter(pk=post_id).exists()

    def liked_post_ids(self, post_ids, user) -> set:
        """IDs (subset of ``post_ids``) the user has liked — one query."""
        from infrastructure.persistence.social.models import Post

        return set(Post.objects.filter(id__in=post_ids, likes=user).values_list("id", flat=True))

    def like_count(self, post) -> int:
        return post.likes.count()

    def toggle_like(self, obj, user):
        """Toggle like on a post. Returns True if liked, False if unliked."""
        # Remove dislike if present
        if user in obj.dislikes.all():
            obj.dislikes.remove(user)
        # Toggle like
        if user in obj.likes.all():
            obj.likes.remove(user)
            return False
        else:
            obj.likes.add(user)
            return True

    # ── Feed post comments ──────────────────────────────────────────────

    def list_post_comments(self, post_id, limit: int = 100):
        from infrastructure.persistence.social.models import Comment

        return list(
            Comment.objects.filter(post_id=post_id, is_deleted=False)
            .select_related("author")
            .order_by("-created_on")[:limit]
        )

    def add_post_comment(self, *, post, author, body: str):
        from infrastructure.persistence.social.models import Comment

        return Comment.objects.create(post=post, author=author, comment=body)

    # ── User display resolution ─────────────────────────────────────────

    def resolve_user_display_names(self, user_ids) -> dict:
        """Batch-resolve ``{user_id: display_name}`` in ONE query (no N+1)."""
        from infrastructure.persistence.users.models import CustomUser

        users = CustomUser.objects.filter(id__in=user_ids).only("id", "first_name", "last_name", "username", "email")
        resolved: dict = {}
        for user in users:
            name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            resolved[str(user.id)] = name or user.username or user.email
        return resolved

    # NOTE: Thread/Message/User-lookup repositories have been extracted to
    # components/messaging/infrastructure/repositories/

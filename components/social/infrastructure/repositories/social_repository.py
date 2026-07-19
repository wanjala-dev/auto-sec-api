"""ORM repository for the social bounded context."""

from __future__ import annotations

from typing import Any, Optional
from django.db.models import Q, QuerySet


class SocialRepository:
    """Encapsulates all ORM access for the social bounded context."""

    # ── Posts ────────────────────────────────────────────────────────────

    def get_post_queryset(self) -> QuerySet:
        from infrastructure.persistence.social.models import Post
        return Post.objects.select_related("author", "shared_user").prefetch_related("likes", "dislikes", "tags", "image")

    def get_post_by_id(self, post_id):
        from infrastructure.persistence.social.models import Post
        return Post.objects.get(pk=post_id)

    def get_followed_posts(self, user_id) -> QuerySet:
        from infrastructure.persistence.social.models import Post
        return Post.objects.filter(author__profile__followers__in=[user_id])

    # ── Comments ────────────────────────────────────────────────────────

    def get_comment_queryset(self) -> QuerySet:
        from infrastructure.persistence.social.models import Comment
        return Comment.objects.select_related("author", "post", "parent").prefetch_related("likes", "dislikes", "tags")

    def get_comment_by_id(self, comment_id):
        from infrastructure.persistence.social.models import Comment
        return Comment.objects.get(pk=comment_id)

    def create_comment(self, *, author, post, parent=None):
        from infrastructure.persistence.social.models import Comment
        comment = Comment(author=author, post=post, parent=parent)
        comment.save()
        return comment

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

        users = CustomUser.objects.filter(id__in=user_ids).only(
            "id", "first_name", "last_name", "username", "email"
        )
        resolved: dict = {}
        for user in users:
            name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            resolved[str(user.id)] = name or user.username or user.email
        return resolved

    # ── Tags ─────────────────────────────────────────────────────────────

    def get_tag_queryset(self) -> QuerySet:
        from infrastructure.persistence.social.models import Tag
        return Tag.objects.all()

    # ── Followers ────────────────────────────────────────────────────────

    def get_user_profile(self, user_id):
        from infrastructure.persistence.users.models import UserProfile
        return UserProfile.objects.get(user=user_id)

    def add_follower(self, profile, follower_id):
        profile.followers.add(follower_id)

    def remove_follower(self, profile, follower_id):
        profile.followers.remove(follower_id)

    def get_followers(self, profile):
        return profile.followers.all()

    # ── Likes / Dislikes ────────────────────────────────────────────────

    def toggle_like(self, obj, user):
        """Toggle like on a post or comment. Returns True if liked, False if unliked."""
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

    def toggle_dislike(self, obj, user):
        """Toggle dislike on a post or comment. Returns True if disliked, False if undisliked."""
        if user in obj.likes.all():
            obj.likes.remove(user)
        if user in obj.dislikes.all():
            obj.dislikes.remove(user)
            return False
        else:
            obj.dislikes.add(user)
            return True

    # NOTE: Thread/Message/User-lookup repositories have been extracted to
    # components/messaging/infrastructure/repositories/

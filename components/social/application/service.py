"""Application service for the social bounded context.

This is the PRIMARY PORT — driving adapters (controllers, CLI, GraphQL)
call these methods to trigger application use cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.social.infrastructure.repositories.social_repository import (
    SocialRepository,
)


@dataclass
class SocialService:
    """Primary port for the social bounded context."""

    _repo: SocialRepository = field(default_factory=SocialRepository)

    # ── Followers ────────────────────────────────────────────────────────

    def get_user_profile(self, user_id):
        return self._repo.get_user_profile(user_id)

    def add_follower(self, user_id, follower_id):
        profile = self._repo.get_user_profile(user_id)
        self._repo.add_follower(profile, follower_id)
        return profile

    def remove_follower(self, user_id, follower_id):
        profile = self._repo.get_user_profile(user_id)
        self._repo.remove_follower(profile, follower_id)
        return profile

    def get_followers(self, user_id):
        profile = self._repo.get_user_profile(user_id)
        return self._repo.get_followers(profile)

    # ── Posts ────────────────────────────────────────────────────────────

    def get_post_queryset(self):
        return self._repo.get_post_queryset()

    def get_post_by_id(self, post_id):
        return self._repo.get_post_by_id(post_id)

    def get_followed_posts(self, user_id):
        return self._repo.get_followed_posts(user_id)

    def toggle_post_like(self, post_id, user):
        post = self._repo.get_post_by_id(post_id)
        liked = self._repo.toggle_like(post, user)
        return post, liked

    def toggle_post_dislike(self, post_id, user):
        post = self._repo.get_post_by_id(post_id)
        self._repo.toggle_dislike(post, user)
        return post

    def resolve_user_display_names(self, user_ids) -> dict:
        if not user_ids:
            return {}
        return self._repo.resolve_user_display_names(user_ids)

    def viewer_liked_post_ids(self, post_ids, viewer) -> set:
        if not post_ids:
            return set()
        return self._repo.liked_post_ids(post_ids, viewer)

    def toggle_feed_post_like(self, post_id, user):
        """Toggle a like on an active feed post.

        Returns ``(liked, like_count)`` or ``None`` when the post doesn't
        exist / is soft-deleted.
        """
        post = self._repo.get_active_post(post_id)
        if post is None:
            return None
        liked = self._repo.toggle_like(post, user)
        return liked, self._repo.like_count(post)

    def post_exists(self, post_id) -> bool:
        return self._repo.post_exists(post_id)

    def list_post_comments(self, post_id, limit: int = 100):
        return self._repo.list_post_comments(post_id, limit=limit)

    def add_post_comment(self, *, post_id, author, body: str):
        """Add a comment to an active post. Returns ``None`` if the post is gone."""
        post = self._repo.get_active_post(post_id)
        if post is None:
            return None
        return self._repo.add_post_comment(post=post, author=author, body=body)

    # ── Comments ────────────────────────────────────────────────────────

    def get_comment_queryset(self):
        return self._repo.get_comment_queryset()

    def get_comment_by_id(self, comment_id):
        return self._repo.get_comment_by_id(comment_id)

    def create_reply(self, *, author, post_id, parent_comment_id):
        post = self._repo.get_post_by_id(post_id)
        parent = self._repo.get_comment_by_id(parent_comment_id)
        return self._repo.create_comment(author=author, post=post, parent=parent), post, parent

    def toggle_comment_like(self, comment_id, user):
        comment = self._repo.get_comment_by_id(comment_id)
        liked = self._repo.toggle_like(comment, user)
        return comment, liked

    def toggle_comment_dislike(self, comment_id, user):
        comment = self._repo.get_comment_by_id(comment_id)
        self._repo.toggle_dislike(comment, user)
        return comment

    # ── Tags ─────────────────────────────────────────────────────────────

    def get_tag_queryset(self):
        return self._repo.get_tag_queryset()

    # NOTE: Threads/Messages have been extracted to components/messaging/
    # See components/messaging/api/urls.py for the new REST endpoints.

"""Application service for the social bounded context.

This is the PRIMARY PORT — driving adapters (controllers, CLI, GraphQL)
call these methods to trigger application use cases.

Scope note: this service now backs ONLY the workspace-feed surface. The
follower / like-dislike / reply / generic-CRUD methods were deleted alongside
the legacy ``/social/`` CRUD views they existed for (retired 2026-08-19 — see
``components/social/api/controller.py``). Post creation, editing, deletion and
feed listing are NOT here: they go through the use cases wired in
``application/providers/feed_provider.py`` against ``PostStorePort``.
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

    # ── Feed post presentation ───────────────────────────────────────────

    def resolve_user_display_names(self, user_ids) -> dict:
        if not user_ids:
            return {}
        return self._repo.resolve_user_display_names(user_ids)

    def viewer_liked_post_ids(self, post_ids, viewer) -> set:
        if not post_ids:
            return set()
        return self._repo.liked_post_ids(post_ids, viewer)

    # ── Feed post interactions ───────────────────────────────────────────

    def toggle_feed_post_like(self, post_id, user):
        """Toggle a like on an active feed post ``user`` can actually see.

        Returns ``(liked, like_count)``, or ``None`` when the post doesn't
        exist, is soft-deleted, or lives outside ``user``'s workspaces. The
        caller renders all three as 404 — a cross-tenant probe must not be
        able to distinguish them.
        """
        post = self._repo.get_visible_active_post(post_id, user)
        if post is None:
            return None
        liked = self._repo.toggle_like(post, user)
        return liked, self._repo.like_count(post)

    def list_post_comments(self, *, post_id, viewer, limit: int = 100):
        """Comments on a post ``viewer`` can see. ``None`` when they cannot.

        ``None`` (not visible / absent) is distinct from ``[]`` (visible, no
        comments) so the controller can 404 the first and 200 the second.
        """
        post = self._repo.get_visible_active_post(post_id, viewer)
        if post is None:
            return None
        return self._repo.list_post_comments(post.pk, limit=limit)

    def add_post_comment(self, *, post_id, author, body: str):
        """Comment on an active post ``author`` can see. ``None`` if they cannot."""
        post = self._repo.get_visible_active_post(post_id, author)
        if post is None:
            return None
        return self._repo.add_post_comment(post=post, author=author, body=body)

    # NOTE: Threads/Messages have been extracted to components/messaging/
    # See components/messaging/api/urls.py for the new REST endpoints.

"""ORM-backed PostStorePort implementation for the feed."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Iterable
from uuid import UUID

from django.db.models import Count, Q
from django.utils import timezone

from components.social.application.ports.post_store_port import (
    CreatePostInput,
    FeedPage,
    PostStorePort,
)
from components.social.domain.entities.post_entity import PostEntity
from components.social.mappers.db.post_mapper import to_post_entity
from infrastructure.persistence.social.models import Post


def _encode_cursor(created_on: datetime, post_id: int) -> str:
    raw = f"{created_on.isoformat()}|{post_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        iso, pid = decoded.rsplit("|", 1)
        return datetime.fromisoformat(iso), int(pid)
    except (ValueError, UnicodeDecodeError):
        return None


class FeedPostRepository(PostStorePort):
    """Concrete feed-post store backed by the ``social.Post`` ORM model."""

    def _base_queryset(self):
        return (
            Post.objects.filter(is_deleted=False)
            .select_related("author", "author__profile", "workspace", "team")
            .prefetch_related("image", "likes", "tags")
            .annotate(
                like_count=Count("likes", distinct=True),
                comment_count=Count("comment", distinct=True),
            )
        )

    def save(self, post: CreatePostInput) -> PostEntity:
        obj = Post.objects.create(
            author_id=post.author_id,
            workspace_id=post.workspace_id,
            team_id=post.team_id,
            visibility=post.visibility.value,
            body=post.body,
        )
        image_ids = list(post.image_ids)
        if image_ids:
            obj.image.add(*image_ids)
        obj.create_tags()
        obj = self._base_queryset().get(pk=obj.pk)
        return to_post_entity(obj)

    def find_by_id(self, post_id: int) -> PostEntity | None:
        obj = self._base_queryset().filter(pk=post_id).first()
        return to_post_entity(obj) if obj is not None else None

    def update_body(
        self, *, post_id: int, body: str, edited_on: datetime
    ) -> PostEntity:
        Post.objects.filter(pk=post_id).update(body=body, edited_on=edited_on)
        obj = self._base_queryset().get(pk=post_id)
        return to_post_entity(obj)

    def soft_delete(self, *, post_id: int) -> None:
        Post.objects.filter(pk=post_id).update(is_deleted=True, edited_on=timezone.now())

    def list_workspace_feed(
        self,
        *,
        viewer_id: UUID,
        workspace_id: UUID,
        followed_user_ids: Iterable[UUID],
        team_id: int | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> FeedPage:
        follow_ids = list(followed_user_ids)
        queryset = self._base_queryset().filter(workspace_id=workspace_id)
        if team_id is not None:
            queryset = queryset.filter(Q(team_id=team_id) | Q(team_id__isnull=True))
        queryset = queryset.filter(
            Q(author_id__in=follow_ids) | Q(author_id=viewer_id)
        )

        decoded = _decode_cursor(cursor)
        if decoded is not None:
            cursor_created, cursor_id = decoded
            queryset = queryset.filter(
                Q(created_on__lt=cursor_created)
                | Q(created_on=cursor_created, id__lt=cursor_id)
            )

        queryset = queryset.order_by("-is_pinned", "-created_on", "-id")
        rows = list(queryset[: limit + 1])

        next_cursor: str | None = None
        if len(rows) > limit:
            tail = rows[limit - 1]
            next_cursor = _encode_cursor(tail.created_on, tail.id)
            rows = rows[:limit]

        return FeedPage(posts=[to_post_entity(r) for r in rows], next_cursor=next_cursor)

"""Response DTOs for the workspace feed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence
from uuid import UUID

from components.social.application.ports.post_store_port import FeedPage
from components.social.domain.entities.post_entity import PostEntity


@dataclass(frozen=True)
class FeedPostResource:
    id: int
    author_id: str
    workspace_id: str | None
    team_id: int | None
    visibility: str
    body: str
    image_ids: tuple[int, ...]
    created_on: str
    edited_on: str | None
    is_pinned: bool
    like_count: int
    comment_count: int

    @classmethod
    def from_entity(cls, post: PostEntity) -> "FeedPostResource":
        return cls(
            id=post.id,
            author_id=str(post.author_id),
            workspace_id=str(post.workspace_id) if post.workspace_id else None,
            team_id=post.team_id,
            visibility=post.visibility.value,
            body=post.body,
            image_ids=post.image_ids,
            created_on=post.created_on.isoformat() if post.created_on else "",
            edited_on=post.edited_on.isoformat() if post.edited_on else None,
            is_pinned=post.is_pinned,
            like_count=post.like_count,
            comment_count=post.comment_count,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "author_id": self.author_id,
            "workspace_id": self.workspace_id,
            "team_id": self.team_id,
            "visibility": self.visibility,
            "body": self.body,
            "image_ids": list(self.image_ids),
            "created_on": self.created_on,
            "edited_on": self.edited_on,
            "is_pinned": self.is_pinned,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
        }


@dataclass(frozen=True)
class FeedPageResource:
    posts: Sequence[FeedPostResource]
    next_cursor: str | None

    @classmethod
    def from_page(cls, page: FeedPage) -> "FeedPageResource":
        return cls(
            posts=[FeedPostResource.from_entity(p) for p in page.posts],
            next_cursor=page.next_cursor,
        )

    def to_dict(self) -> dict:
        return {
            "posts": [p.to_dict() for p in self.posts],
            "next_cursor": self.next_cursor,
        }

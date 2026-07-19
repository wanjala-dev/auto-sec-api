"""Port for persisting and reading feed posts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence
from uuid import UUID

from components.social.domain.entities.post_entity import PostEntity, PostVisibility


@dataclass(frozen=True)
class FeedPage:
    posts: Sequence[PostEntity]
    next_cursor: str | None


@dataclass(frozen=True)
class CreatePostInput:
    author_id: UUID
    workspace_id: UUID | None
    team_id: int | None
    visibility: PostVisibility
    body: str
    image_ids: Iterable[int] = ()


class PostStorePort(ABC):
    @abstractmethod
    def save(self, post: CreatePostInput) -> PostEntity:
        ...

    @abstractmethod
    def find_by_id(self, post_id: int) -> PostEntity | None:
        ...

    @abstractmethod
    def update_body(self, *, post_id: int, body: str, edited_on: datetime) -> PostEntity:
        ...

    @abstractmethod
    def soft_delete(self, *, post_id: int) -> None:
        ...

    @abstractmethod
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
        ...

"""Post domain entity.

Immutable representation of a feed post — no ORM, no DRF, no Django imports.
The application layer operates on :class:`PostEntity`; mappers translate to
and from the ORM model at the infrastructure boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Tuple
from uuid import UUID


class PostVisibility(str, Enum):
    WORKSPACE = "workspace"
    TEAM = "team"
    PUBLIC = "public"


@dataclass(frozen=True)
class PostEntity:
    id: int | None
    author_id: UUID
    workspace_id: UUID | None
    team_id: int | None
    visibility: PostVisibility
    body: str
    image_ids: Tuple[int, ...] = field(default_factory=tuple)
    created_on: datetime | None = None
    edited_on: datetime | None = None
    is_pinned: bool = False
    is_deleted: bool = False
    like_count: int = 0
    comment_count: int = 0

    def __post_init__(self) -> None:
        if not self.body or not self.body.strip():
            raise ValueError("Post body cannot be empty.")
        if self.visibility == PostVisibility.TEAM and self.team_id is None:
            raise ValueError("team-scoped posts require a team_id.")
        if self.visibility in (PostVisibility.WORKSPACE, PostVisibility.TEAM) and self.workspace_id is None:
            raise ValueError("workspace- or team-scoped posts require a workspace_id.")

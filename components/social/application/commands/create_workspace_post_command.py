"""Command for creating a workspace or team feed post."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID

from components.social.domain.entities.post_entity import PostVisibility


@dataclass(frozen=True)
class CreateWorkspacePostCommand:
    author_id: UUID
    workspace_id: UUID
    team_id: int | None
    visibility: PostVisibility
    body: str
    image_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def build(
        cls,
        *,
        author_id: UUID,
        workspace_id: UUID,
        body: str,
        team_id: int | None = None,
        visibility: str | PostVisibility | None = None,
        image_ids: Iterable[int] = (),
    ) -> "CreateWorkspacePostCommand":
        if visibility is None:
            resolved = PostVisibility.TEAM if team_id is not None else PostVisibility.WORKSPACE
        else:
            resolved = PostVisibility(visibility) if isinstance(visibility, str) else visibility
        return cls(
            author_id=author_id,
            workspace_id=workspace_id,
            team_id=team_id,
            visibility=resolved,
            body=body,
            image_ids=tuple(image_ids),
        )

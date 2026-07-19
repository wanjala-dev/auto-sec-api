"""Request DTO for creating a workspace feed post."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID

from components.social.domain.entities.post_entity import PostVisibility


@dataclass(frozen=True)
class CreateFeedPostRequest:
    body: str
    team_id: int | None
    visibility: PostVisibility
    image_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CreateFeedPostRequest":
        body = (payload.get("body") or "").strip()
        team_id_raw = payload.get("team_id")
        team_id = int(team_id_raw) if team_id_raw not in (None, "", "null") else None
        visibility_raw = payload.get("visibility")
        if visibility_raw:
            visibility = PostVisibility(visibility_raw)
        else:
            visibility = PostVisibility.TEAM if team_id is not None else PostVisibility.WORKSPACE
        image_ids = payload.get("image_ids") or []
        if isinstance(image_ids, (str, bytes)):
            image_ids = [image_ids]
        image_ids_clean = tuple(int(x) for x in image_ids if str(x).strip())
        return cls(body=body, team_id=team_id, visibility=visibility, image_ids=image_ids_clean)

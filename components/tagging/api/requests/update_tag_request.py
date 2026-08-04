"""Input DTO for PATCH /tagging/workspaces/<ws>/tags/<tag_id>/ (ADR 0015 D5/D6).

Absent field = leave unchanged. ``is_deleted: false`` = restore (subject to the
live-uniqueness check); ``is_deleted: true`` = soft delete.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.tagging.application.commands.update_tag_command import UpdateTagCommand


def _optional_str(data: dict, key: str) -> str | None:
    if key not in data:
        return None
    raw = data.get(key)
    if not isinstance(raw, str):
        raise ValidationError({key: "Must be a string."})
    return raw


@dataclass(frozen=True)
class UpdateTagRequest:
    workspace_id: UUID
    tag_id: UUID
    name: str | None
    color: str | None
    description: str | None
    is_deleted: bool | None
    actor_id: str | None

    @classmethod
    def from_request(cls, request, workspace_id, tag_id) -> UpdateTagRequest:
        data = request.data or {}
        is_deleted = None
        if "is_deleted" in data:
            if not isinstance(data["is_deleted"], bool):
                raise ValidationError({"is_deleted": "Must be a boolean."})
            is_deleted = data["is_deleted"]
        return cls(
            workspace_id=workspace_id,
            tag_id=tag_id,
            name=_optional_str(data, "name"),
            color=_optional_str(data, "color"),
            description=_optional_str(data, "description"),
            is_deleted=is_deleted,
            actor_id=str(getattr(request.user, "id", "") or "") or None,
        )

    def to_command(self) -> UpdateTagCommand:
        return UpdateTagCommand(
            workspace_id=self.workspace_id,
            tag_id=self.tag_id,
            name=self.name,
            color=self.color,
            description=self.description,
            is_deleted=self.is_deleted,
            actor_id=self.actor_id,
        )

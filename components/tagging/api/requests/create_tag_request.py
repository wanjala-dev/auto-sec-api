"""Input DTO for POST /tagging/workspaces/<ws>/tags/ (ADR 0015 D6)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.tagging.application.commands.create_tag_command import CreateTagCommand


def _str_field(data: dict, key: str, *, required: bool = False) -> str:
    raw = data.get(key)
    if raw is None:
        if required:
            raise ValidationError({key: "This field is required."})
        return ""
    if not isinstance(raw, str):
        raise ValidationError({key: "Must be a string."})
    if required and not raw.strip():
        raise ValidationError({key: "This field is required."})
    return raw


@dataclass(frozen=True)
class CreateTagRequest:
    workspace_id: UUID
    name: str
    namespace: str
    color: str
    description: str
    actor_id: str | None

    @classmethod
    def from_request(cls, request, workspace_id) -> CreateTagRequest:
        data = request.data or {}
        return cls(
            workspace_id=workspace_id,
            name=_str_field(data, "name", required=True),
            namespace=_str_field(data, "namespace").strip(),
            color=_str_field(data, "color").strip(),
            description=_str_field(data, "description"),
            actor_id=str(getattr(request.user, "id", "") or "") or None,
        )

    def to_command(self) -> CreateTagCommand:
        # ``kind`` is never client-settable — user CRUD creates user tags only (D4/D8).
        return CreateTagCommand(
            workspace_id=self.workspace_id,
            name=self.name,
            namespace=self.namespace,
            color=self.color,
            description=self.description,
            kind="user",
            actor_id=self.actor_id,
        )

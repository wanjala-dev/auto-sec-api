"""Input DTO for POST /findings/workspaces/<ws>/<finding_id>/tags/ (ADR 0015 D6).

Body: ``{"add": [slugs…], "remove": [slugs…]}`` — both optional, at least one
non-empty. ONE endpoint subsumes apply + remove (no separate DELETE route),
matching the status endpoint's single-POST action shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.findings.application.commands.tag_finding_command import TagFindingCommand


def _slug_list(data: dict, key: str) -> tuple[str, ...]:
    raw = data.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValidationError({key: "must be a list of strings"})
    return tuple(s.strip() for s in raw if s.strip())


@dataclass(frozen=True)
class TagFindingRequest:
    workspace_id: UUID
    finding_id: UUID
    add: tuple[str, ...]
    remove: tuple[str, ...]
    actor_id: str | None

    @classmethod
    def from_request(cls, request, workspace_id, finding_id) -> TagFindingRequest:
        data = request.data or {}
        add = _slug_list(data, "add")
        remove = _slug_list(data, "remove")
        if not add and not remove:
            raise ValidationError({"add": "provide at least one slug in 'add' or 'remove'"})
        return cls(
            workspace_id=workspace_id,
            finding_id=finding_id,
            add=add,
            remove=remove,
            actor_id=str(getattr(request.user, "id", "") or "") or None,
        )

    def to_command(self, *, at: datetime) -> TagFindingCommand:
        return TagFindingCommand(
            workspace_id=self.workspace_id,
            finding_id=self.finding_id,
            add=self.add,
            remove=self.remove,
            actor_id=self.actor_id,
            at=at,
        )

"""Input DTO for the finding status-change API — parses + validates the action."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.findings.application.commands.change_finding_status_command import (
    VALID_ACTIONS,
    ChangeFindingStatusCommand,
)


@dataclass(frozen=True)
class ChangeFindingStatusRequest:
    workspace_id: UUID
    finding_id: UUID
    action: str
    actor_id: str | None

    @classmethod
    def from_request(cls, request, workspace_id, finding_id) -> ChangeFindingStatusRequest:
        action = str((request.data or {}).get("action") or "").strip().lower()
        if action not in VALID_ACTIONS:
            raise ValidationError({"action": f"must be one of {sorted(VALID_ACTIONS)}"})
        return cls(
            workspace_id=workspace_id,
            finding_id=finding_id,
            action=action,
            actor_id=str(getattr(request.user, "id", "") or "") or None,
        )

    def to_command(self, *, at: datetime) -> ChangeFindingStatusCommand:
        return ChangeFindingStatusCommand(
            workspace_id=self.workspace_id,
            finding_id=self.finding_id,
            action=self.action,
            at=at,
            actor_id=self.actor_id,
        )

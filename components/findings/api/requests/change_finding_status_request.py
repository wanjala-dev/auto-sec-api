"""Input DTO for the finding status-change API — parses + validates the action."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from rest_framework.exceptions import ValidationError

from components.findings.application.commands.change_finding_status_command import (
    VALID_ACTIONS,
    ChangeFindingStatusCommand,
)


def _parse_expires_at(raw) -> datetime | None:
    """Parse the optional suppress expiry (ISO-8601). Normalized to the project's
    datetime convention: naive when ``USE_TZ=False`` (base), aware when True (tests) —
    so the ORM never mixes naive/aware datetimes."""
    if raw in (None, ""):
        return None
    from django.conf import settings
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(str(raw))
    if parsed is None:
        raise ValidationError({"expires_at": "must be an ISO-8601 datetime"})
    if settings.USE_TZ and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    elif not settings.USE_TZ and timezone.is_aware(parsed):

        parsed = timezone.make_naive(parsed, UTC)
    return parsed


@dataclass(frozen=True)
class ChangeFindingStatusRequest:
    workspace_id: UUID
    finding_id: UUID
    action: str
    actor_id: str | None
    reason: str = ""
    expires_at: datetime | None = None

    @classmethod
    def from_request(cls, request, workspace_id, finding_id) -> ChangeFindingStatusRequest:
        data = request.data or {}
        action = str(data.get("action") or "").strip().lower()
        if action not in VALID_ACTIONS:
            raise ValidationError({"action": f"must be one of {sorted(VALID_ACTIONS)}"})
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValidationError({"reason": "must be a string"})
        return cls(
            workspace_id=workspace_id,
            finding_id=finding_id,
            action=action,
            actor_id=str(getattr(request.user, "id", "") or "") or None,
            reason=(reason or "").strip(),
            expires_at=_parse_expires_at(data.get("expires_at")),
        )

    def to_command(self, *, at: datetime) -> ChangeFindingStatusCommand:
        return ChangeFindingStatusCommand(
            workspace_id=self.workspace_id,
            finding_id=self.finding_id,
            action=self.action,
            at=at,
            actor_id=self.actor_id,
            reason=self.reason,
            expires_at=self.expires_at,
        )

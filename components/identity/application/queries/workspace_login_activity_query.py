"""Read DTO for the org-level (workspace-scoped) login-activity list."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class WorkspaceLoginActivityQuery:
    """Filters for a workspace's login-activity feed (admin surface).

    The read model resolves the workspace's ACTIVE members (plus the
    workspace owner, who may not hold a membership row) at read time,
    restricts to the login-ish event codes
    (``LOGIN_ACTIVITY_EVENT_CODES``), and subtracts the events this
    workspace has hidden via ``WorkspaceLoginActivityExclusion``.

    ``created_from`` / ``created_to`` are inclusive datetime bounds
    already parsed by the controller.
    """

    workspace_id: UUID
    user_id: UUID | None = None
    event_code: str | None = None
    success: bool | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None

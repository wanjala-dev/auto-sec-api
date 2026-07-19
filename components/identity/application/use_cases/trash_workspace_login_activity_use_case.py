"""Use case: hide one login-activity event from a workspace's org view.

The "delete" is a per-workspace exclusion row, recorded in the recycle
bin so it is restorable — the append-only ``AuthAuditEvent`` is NEVER
mutated or destroyed. The member keeps their own /me/login-activity/
history and other workspaces are unaffected.

Flow:
1. Validate the event exists, is login-ish, and belongs to an ACTIVE
   member (or the owner) of the workspace — else
   ``LoginActivityEventNotFoundError`` (→ 404 at the HTTP edge).
2. Idempotently create the ``WorkspaceLoginActivityExclusion`` row —
   the event disappears from this org's list immediately.
3. On first creation only, record a recycle-bin entry
   (entity_type ``login_activity``, entity_id = the exclusion UUID —
   satisfies the bin's global unique(entity_type, entity_id) and scopes
   naturally to the workspace). The bin calls back into
   ``LoginActivitySoftDeleteAdapter.soft_delete`` for the display
   snapshot; restore deletes the exclusion row so the event reappears.

Framework-free — the recycle-bin collaborator is the recycle_bin
context's application service (cross-context application import,
allowed), injected so unit tests can pass a fake.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.identity.application.ports.login_activity_exclusion_port import LoginActivityExclusionPort
from components.identity.application.ports.login_activity_query_port import LoginActivityQueryPort
from components.identity.domain.errors import LoginActivityEventNotFoundError
from components.recycle_bin.application.commands.trash_command import TrashCommand

logger = logging.getLogger(__name__)

LOGIN_ACTIVITY_ENTITY_TYPE = "login_activity"


class TrashWorkspaceLoginActivityUseCase:
    """Hide an event from ONE workspace's login-activity view, restorably."""

    def __init__(
        self,
        *,
        activity_port: LoginActivityQueryPort,
        exclusion_port: LoginActivityExclusionPort,
        recycle_bin,
        visibility_policy: OrgAuditVisibilityPolicy,
    ) -> None:
        self._activity = activity_port
        self._exclusions = exclusion_port
        self._recycle_bin = recycle_bin
        self._visibility = visibility_policy

    def execute(self, *, workspace_id: UUID, event_id: int, deleted_by: UUID) -> UUID:
        self._visibility.ensure_visible(workspace_id)
        event = self._activity.get_workspace_event(workspace_id=workspace_id, event_id=event_id)
        if event is None:
            raise LoginActivityEventNotFoundError(
                f"Login-activity event {event_id} does not belong to a member of workspace {workspace_id}."
            )

        exclusion_id, created = self._exclusions.get_or_create(
            workspace_id=workspace_id,
            event_id=event_id,
            hidden_by=deleted_by,
        )
        if not created:
            # Already hidden for this workspace — idempotent no-op; the
            # bin entry from the first hide already exists.
            return exclusion_id

        self._recycle_bin.trash(
            TrashCommand(
                workspace_id=workspace_id,
                entity_type=LOGIN_ACTIVITY_ENTITY_TYPE,
                entity_id=str(exclusion_id),
                deleted_by=deleted_by,
            )
        )
        logger.info(
            "workspace_login_activity_hidden workspace_id=%s event_id=%s exclusion_id=%s hidden_by=%s",
            workspace_id,
            event_id,
            exclusion_id,
            deleted_by,
        )
        return exclusion_id

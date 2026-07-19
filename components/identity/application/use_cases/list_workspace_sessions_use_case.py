"""Use case: list a workspace's members' ACTIVE login sessions.

Framework-free. Active means not revoked and not expired; rows are
ordered by ``-last_seen_at`` and capped (default 200) — an admin
overview, not a paginated archive. Each row carries its owning user
(eager-loaded by the adapter).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from components.identity.application.policies.org_audit_visibility_policy import OrgAuditVisibilityPolicy
from components.identity.application.ports.login_activity_query_port import LoginActivityQueryPort

MAX_WORKSPACE_SESSIONS = 200


class ListWorkspaceSessionsUseCase:
    """Org-admin view of the members' currently-active sessions."""

    def __init__(
        self,
        *,
        activity_port: LoginActivityQueryPort,
        visibility_policy: OrgAuditVisibilityPolicy,
    ) -> None:
        self._activity = activity_port
        self._visibility = visibility_policy

    def execute(self, *, workspace_id: UUID) -> Sequence:
        self._visibility.ensure_visible(workspace_id)
        return self._activity.list_active_workspace_sessions(
            workspace_id=workspace_id,
            limit=MAX_WORKSPACE_SESSIONS,
        )

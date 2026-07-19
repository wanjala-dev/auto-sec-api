"""Use case: list a workspace's org-level login activity (admin surface).

Framework-free — delegates to the workspace scope of the login-activity
read port. The result is a sliceable sequence the REST adapter
paginates; each row carries its linked session AND user (eager-loaded
by the adapter, so serialising the member + device summary costs no
extra queries). Full detail — including ip_address and raw user_agent —
is intentionally exposed to org admins (decided 2026-07).
"""

from __future__ import annotations

from collections.abc import Sequence

from components.identity.application.policies.org_audit_visibility_policy import OrgAuditVisibilityPolicy
from components.identity.application.ports.login_activity_query_port import LoginActivityQueryPort
from components.identity.application.queries.workspace_login_activity_query import WorkspaceLoginActivityQuery


class ListWorkspaceLoginActivityUseCase:
    """Org-admin view of the members' login-ish audit trail."""

    def __init__(
        self,
        *,
        activity_port: LoginActivityQueryPort,
        visibility_policy: OrgAuditVisibilityPolicy,
    ) -> None:
        self._activity = activity_port
        self._visibility = visibility_policy

    def execute(self, query: WorkspaceLoginActivityQuery) -> Sequence:
        self._visibility.ensure_visible(query.workspace_id)
        return self._activity.list_for_workspace(query)

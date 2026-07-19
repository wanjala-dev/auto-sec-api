"""Application policy: is the org audit-log surface visible for a workspace?

Single evaluator consulted by all three org-level use cases (list
login activity, list sessions, trash an event) so the "toggle off →
403 org_audit_log_disabled" rule lives in ONE place instead of being
copy-pasted per controller/use case.

Visibility only — auth events keep recording regardless of the toggle.
Framework-free: depends on the settings port and a domain error.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.org_audit_log_settings_port import OrgAuditLogSettingsPort
from components.identity.domain.errors import OrgAuditLogDisabledError


class OrgAuditVisibilityPolicy:
    """Raise ``OrgAuditLogDisabledError`` when the workspace toggle is OFF."""

    def __init__(self, *, settings_port: OrgAuditLogSettingsPort) -> None:
        self._settings = settings_port

    def ensure_visible(self, workspace_id: UUID) -> None:
        if not self._settings.is_enabled(workspace_id):
            raise OrgAuditLogDisabledError("The organization audit log has been turned off by a workspace admin.")

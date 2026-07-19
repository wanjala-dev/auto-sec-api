"""Use case: flip a workspace's org audit-log visibility toggle.

Framework-free. Visibility only — turning the toggle off never stops
auth-event collection; it hides the org admin surfaces until an admin
turns it back on (this use case itself is therefore NOT gated by the
toggle).
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.identity.application.ports.org_audit_log_settings_port import OrgAuditLogSettingsPort

logger = logging.getLogger(__name__)


class SetOrgAuditLogSettingsUseCase:
    """Admin write of the per-workspace ``audit_log_enabled`` toggle."""

    def __init__(self, *, settings_port: OrgAuditLogSettingsPort) -> None:
        self._settings = settings_port

    def execute(self, *, workspace_id: UUID, enabled: bool, changed_by: UUID) -> bool:
        stored = self._settings.set_enabled(workspace_id, bool(enabled))
        logger.info(
            "org_audit_log_toggle_set workspace_id=%s enabled=%s changed_by=%s",
            workspace_id,
            stored,
            changed_by,
        )
        return stored

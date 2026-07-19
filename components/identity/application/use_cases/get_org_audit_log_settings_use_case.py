"""Use case: read a workspace's org audit-log visibility toggle.

Framework-free. NOT gated by the toggle itself — an admin must be able
to see ``enabled=False`` in order to flip it back on.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.org_audit_log_settings_port import OrgAuditLogSettingsPort


class GetOrgAuditLogSettingsUseCase:
    """Admin read of the per-workspace ``audit_log_enabled`` toggle."""

    def __init__(self, *, settings_port: OrgAuditLogSettingsPort) -> None:
        self._settings = settings_port

    def execute(self, *, workspace_id: UUID) -> bool:
        return self._settings.is_enabled(workspace_id)

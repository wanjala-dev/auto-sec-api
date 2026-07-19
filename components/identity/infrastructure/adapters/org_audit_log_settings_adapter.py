"""Adapter: org audit-log toggle backed by the shared WorkspacePreference.

REUSE, not a new model: the per-workspace settings bag already exists
(``notifications.userpreferences.WorkspacePreference`` — a OneToOne
JSONField that carries notification + financial-report preferences).
The toggle is one boolean key (``audit_log_enabled``) in that bag, with
its default merged in by ``WorkspacePreference.get_settings()`` /
``default_workspace_preference_settings()`` — no schema migration, no
parallel settings table.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.org_audit_log_settings_port import OrgAuditLogSettingsPort
from infrastructure.persistence.notifications.userpreferences.models import (
    AUDIT_LOG_ENABLED_DEFAULT,
    AUDIT_LOG_ENABLED_KEY,
    WorkspacePreference,
)


class WorkspacePreferenceOrgAuditLogSettingsAdapter(OrgAuditLogSettingsPort):
    """Read/write ``audit_log_enabled`` in the workspace's JSON settings."""

    def is_enabled(self, workspace_id: UUID) -> bool:
        preference = WorkspacePreference.objects.filter(workspace_id=workspace_id).only("settings").first()
        if preference is None:
            return AUDIT_LOG_ENABLED_DEFAULT
        return bool(preference.get_settings().get(AUDIT_LOG_ENABLED_KEY, AUDIT_LOG_ENABLED_DEFAULT))

    def set_enabled(self, workspace_id: UUID, enabled: bool) -> bool:
        preference, _created = WorkspacePreference.objects.get_or_create(workspace_id=workspace_id)
        preference.update_settings({AUDIT_LOG_ENABLED_KEY: bool(enabled)})
        return bool(preference.get_settings()[AUDIT_LOG_ENABLED_KEY])

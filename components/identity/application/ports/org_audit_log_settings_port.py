"""Port: per-workspace org audit-log visibility settings.

Backs the admin toggle that hides/shows the org-level login-activity +
sessions surfaces. Storage is the shared ``WorkspacePreference`` JSON
settings bag (reused — no parallel settings model); this port keeps the
identity application layer ignorant of where the bit lives.

The toggle controls VISIBILITY only — auth-event collection is never
gated by it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class OrgAuditLogSettingsPort(ABC):
    """Read/write the per-workspace ``audit_log_enabled`` toggle."""

    @abstractmethod
    def is_enabled(self, workspace_id: UUID) -> bool:
        """Return the toggle for the workspace (default True when unset)."""

    @abstractmethod
    def set_enabled(self, workspace_id: UUID, enabled: bool) -> bool:
        """Persist the toggle and return the stored value."""

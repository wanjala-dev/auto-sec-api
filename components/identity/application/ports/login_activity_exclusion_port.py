"""Port for the per-workspace login-activity exclusion store.

An exclusion row hides ONE audit event from ONE workspace's org-level
login-activity view. The underlying ``AuthAuditEvent`` is append-only
and is never mutated — the member keeps their own history and other
workspaces are unaffected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class LoginActivityExclusionPort(ABC):
    """Secondary/driven port for workspace login-activity exclusions."""

    @abstractmethod
    def get_or_create(self, *, workspace_id: UUID, event_id: int, hidden_by: UUID) -> tuple[UUID, bool]:
        """Idempotently record that ``event_id`` is hidden for
        ``workspace_id``. Returns ``(exclusion_id, created)`` —
        ``created`` is False when the event was already hidden (the
        existing row's id is returned unchanged)."""

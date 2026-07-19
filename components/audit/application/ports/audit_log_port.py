"""Port interface for the audit log write/read store.

Application use cases depend on this abstract interface, not on the
Django ORM adapter. Keeps the application layer framework-free per
the Explicit Architecture rules in CLAUDE.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from components.audit.domain.entities.audit_entry_entity import AuditEntry


class AuditLogPort(ABC):
    """Persistence contract for ``EntityAuditLog`` rows."""

    @abstractmethod
    def record(
        self,
        *,
        workspace_id: str | None,
        entity_type: str,
        entity_id: str,
        field_name: str,
        previous_value: Any,
        new_value: Any,
        actor_id: str | None,
        reason: str,
    ) -> AuditEntry | None:
        """Persist one audit row.

        Returns the saved entry, or ``None`` when the call is a
        no-op (``previous_value == new_value``). Implementations
        MUST guard against identity edits so callers don't need to.
        """

    @abstractmethod
    def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        field_name: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """Return history for a specific entity, newest first.

        Optionally narrow to a single ``field_name``.
        """

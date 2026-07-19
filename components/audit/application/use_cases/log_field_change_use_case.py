"""Use case: write one audit log entry for a field change.

Framework-free. Orchestrates the port plus value normalisation
(Decimal, UUID, datetime → JSON-safe) so callers don't have to
worry about serialisation quirks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.audit.application.ports.audit_log_port import AuditLogPort
from components.audit.domain.entities.audit_entry_entity import AuditEntry


def _json_safe(value: Any) -> Any:
    """Coerce a value into something ``JSONField`` stores losslessly."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


@dataclass
class LogFieldChangeUseCase:
    audit_log: AuditLogPort

    def execute(
        self,
        *,
        workspace_id: str | None,
        entity_type: str,
        entity_id: str,
        field_name: str,
        previous_value: Any,
        new_value: Any,
        actor_id: str | None,
        reason: str = "",
    ) -> AuditEntry | None:
        serialised_previous = _json_safe(previous_value)
        serialised_new = _json_safe(new_value)
        if serialised_previous == serialised_new:
            return None
        return self.audit_log.record(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            previous_value=serialised_previous,
            new_value=serialised_new,
            actor_id=actor_id,
            reason=reason or "",
        )

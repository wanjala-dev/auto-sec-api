"""Use case: list audit entries for a specific entity."""

from __future__ import annotations

from dataclasses import dataclass

from components.audit.application.ports.audit_log_port import AuditLogPort
from components.audit.domain.entities.audit_entry_entity import AuditEntry


@dataclass
class GetEntityHistoryUseCase:
    audit_log: AuditLogPort

    def execute(
        self,
        *,
        entity_type: str,
        entity_id: str,
        field_name: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        return self.audit_log.list_for_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            limit=limit,
        )

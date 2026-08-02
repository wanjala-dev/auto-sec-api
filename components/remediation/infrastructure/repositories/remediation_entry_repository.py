"""Django repository implementing RemediationEntryStorePort.

Every read goes through the ``.active`` manager (non-revoked) and is filtered by
``workspace_id`` — the D4 tenant boundary is enforced at the data layer, not by a
prompt or a caller's discipline. ``save`` is the single persistence path, reached
only from the gated use case.
"""

from __future__ import annotations

from uuid import UUID

from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.mappers.db.remediation_entry_mapper import to_entity, to_row_fields


class DjangoRemediationEntryRepository(RemediationEntryStorePort):
    def save(self, entry: RemediationEntry) -> RemediationEntry:
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        row, _ = Row.objects.update_or_create(
            id=entry.id,
            defaults={"workspace_id": entry.workspace_id, **to_row_fields(entry)},
        )
        return to_entity(row)

    def get(self, entry_id: UUID, *, workspace_id: UUID) -> RemediationEntry | None:
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        row = Row.active.select_related("workspace").filter(id=entry_id, workspace_id=workspace_id).first()
        return to_entity(row) if row is not None else None

    def find_by_finding_task(self, *, workspace_id: UUID, finding_task_id: str) -> RemediationEntry | None:
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        row = (
            Row.active.select_related("workspace")
            .filter(workspace_id=workspace_id, finding_task_id=finding_task_id)
            .order_by("-created_at")
            .first()
        )
        return to_entity(row) if row is not None else None

    def list_for_workspace(self, workspace_id: UUID, *, limit: int = 50) -> list[RemediationEntry]:
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        qs = Row.active.select_related("workspace").filter(workspace_id=workspace_id)
        return [to_entity(row) for row in qs.order_by("-created_at")[: max(1, int(limit))]]

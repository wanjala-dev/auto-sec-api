"""Django repository implementing RemediationEntryStorePort.

Every read goes through the ``.active`` manager (non-revoked) and is filtered by
``workspace_id`` — the D4 tenant boundary is enforced at the data layer, not by a
prompt or a caller's discipline. ``save`` is the single persistence path, reached
only from the gated use case.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.remediation.application.ports.remediation_entry_store_port import (
    RemediationEntryStorePort,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry
from components.remediation.mappers.db.remediation_entry_mapper import to_entity, to_row_fields

logger = logging.getLogger(__name__)


class DjangoRemediationEntryRepository(RemediationEntryStorePort):
    def save(self, entry: RemediationEntry) -> RemediationEntry:
        from django.db import IntegrityError, transaction

        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        try:
            # atomic() so a constraint violation cleanly rolls back THIS write and
            # leaves the connection usable for the follow-up read (Postgres aborts
            # the whole transaction on an IntegrityError otherwise).
            with transaction.atomic():
                row, _ = Row.objects.update_or_create(
                    id=entry.id,
                    defaults={"workspace_id": entry.workspace_id, **to_row_fields(entry)},
                )
            return to_entity(row)
        except IntegrityError:
            # The partial unique constraint (uniq_active_remediation_per_finding)
            # fired: a CONCURRENT insert already created the one-active-entry-per-fix
            # row for this (workspace, finding_task_id). That is exactly the
            # idempotent outcome — return the existing row instead of raising.
            #
            # We classify by OBSERVABLE STATE (is there now an active row for this
            # finding?), not by parsing the vendor error string — the message differs
            # across Postgres (carries the constraint name) and SQLite (carries only
            # the columns), so a substring match would be backend-fragile. If NO
            # active row is visible, this was some OTHER integrity error → re-raise.
            existing = self.find_by_finding_task(workspace_id=entry.workspace_id, finding_task_id=entry.finding_task_id)
            if existing is None:
                raise
            logger.info(
                "remediation_entry_save idempotent_insert_race workspace_id=%s finding_task_id=%s entry_id=%s",
                entry.workspace_id,
                entry.finding_task_id,
                existing.id,
            )
            return existing

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

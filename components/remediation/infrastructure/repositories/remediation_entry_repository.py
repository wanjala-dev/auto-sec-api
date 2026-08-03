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

    def find_active_priors(
        self,
        *,
        workspace_id: UUID,
        finding_kind: str,
        exclude_entry_id: UUID,
        limit: int = 50,
    ) -> list[RemediationEntry]:
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        qs = (
            Row.active.select_related("workspace")
            .filter(workspace_id=workspace_id, finding_kind=finding_kind)
            .exclude(id=exclude_entry_id)
            .order_by("-created_at")
        )
        return [to_entity(row) for row in qs[: max(1, int(limit))]]

    def filter_active_entry_ids(self, *, workspace_id, entry_ids: list[str]) -> set[str]:
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        ids = [str(e) for e in (entry_ids or []) if e]
        if not ids:
            return set()
        # Bounded by the retrieval pool (top-k) and workspace-scoped. Reads the
        # ``.active`` manager so a soft-deleted (revoked) entry is absent — that is
        # the authority that makes a revoked entry unretrievable regardless of the
        # embedding-delete's fate.
        rows = Row.active.filter(workspace_id=workspace_id, id__in=ids).values_list("id", flat=True)
        return {str(rid) for rid in rows}

    # ── Outcome mutations (P5) — the ONLY corpus writes besides the gate save ──
    # These live here (the sole-writer repository) because ANY RemediationEntry ORM
    # write must (ADR 0012 D1). Each re-derives ``score`` from the bumped counters
    # via the domain ranking policy — never from caller input — under a row lock so
    # concurrent outcomes don't lose an increment.

    def record_reuse_success(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        return self._bump_outcome(entry_id=entry_id, workspace_id=workspace_id, reuse=1, success=1, recurrence=0)

    def record_recurrence(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        return self._bump_outcome(entry_id=entry_id, workspace_id=workspace_id, reuse=0, success=0, recurrence=1)

    def _bump_outcome(
        self,
        *,
        entry_id: UUID,
        workspace_id: UUID,
        reuse: int,
        success: int,
        recurrence: int,
    ) -> RemediationEntry | None:
        from django.db import transaction
        from django.utils import timezone

        from components.remediation.domain.services.remediation_ranking_policy import (
            RemediationRankingPolicy,
        )
        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        with transaction.atomic():
            # Lock the active row so parallel outcome writes serialise (no lost
            # increment). A revoked/foreign row resolves to None and mutates nothing.
            row = Row.active.select_for_update().filter(id=entry_id, workspace_id=workspace_id).first()
            if row is None:
                return None
            row.reuse_count = int(row.reuse_count) + reuse
            row.success_count = int(row.success_count) + success
            row.recurrence_count = int(row.recurrence_count) + recurrence
            row.score = RemediationRankingPolicy.derive_score(
                reuse_count=row.reuse_count,
                success_count=row.success_count,
                recurrence_count=row.recurrence_count,
            )
            row.last_outcome_at = timezone.now()
            row.save(update_fields=["reuse_count", "success_count", "recurrence_count", "score", "last_outcome_at"])
        logger.info(
            "remediation_outcome_recorded entry_id=%s workspace_id=%s reuse=%s success=%s recurrence=%s score=%s",
            entry_id,
            workspace_id,
            row.reuse_count,
            row.success_count,
            row.recurrence_count,
            row.score,
        )
        return to_entity(row)

    def revoke(
        self,
        *,
        entry_id: UUID,
        workspace_id: UUID,
        revoked_by: str,
        reason: str,
    ) -> RemediationEntry | None:
        from django.db import transaction

        from infrastructure.persistence.remediation.models import RemediationEntry as Row

        with transaction.atomic():
            # Scope to the workspace (D4): a foreign id revokes nothing. Use the base
            # manager (not ``active``) so revoking an already-revoked entry is an
            # idempotent no-op that still returns the (already soft-deleted) row.
            row = Row.objects.select_for_update().filter(id=entry_id, workspace_id=workspace_id).first()
            if row is None:
                return None
            if not row.is_deleted:
                row.is_deleted = True
                row.save(update_fields=["is_deleted", "updated_at"])
        logger.info(
            "remediation_entry_revoked entry_id=%s workspace_id=%s revoked_by=%s",
            entry_id,
            workspace_id,
            revoked_by,
        )
        return to_entity(row)

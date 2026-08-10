"""ORM adapter: archive a suppressed finding's board card(s) into the recycle bin.

Implements :class:`ArchiveFindingCardsPort`. The project context owns the board
``Task``, so THIS is the sanctioned place the suppressed-card archive is written
(architecture skill C2), and the archive itself is delegated to the recycle_bin
application service — the EXACT path the HUD's card delete uses
(``TaskUpdateView.delete`` → ``get_recycle_bin_service().trash`` →
``TaskSoftDeleteAdapter``), so the card lands in the board's RECYCLE BIN tray
and the existing restore flow works unchanged. Never a delete.

Before the trash, each card gets a provenance event + a card comment naming why
it was archived (finding suppressed + the operator's reason) — the same growable
``metadata.provenance`` shape the detector/triage/draft-PR pipeline appends to —
so the "every AI action lands on the board as provenance" principle holds even
for a card the operator will mostly see post-restore.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from components.project.application.ports.archive_finding_cards_port import (
    ArchiveFindingCardsCommand,
    ArchiveFindingCardsPort,
    ArchiveFindingCardsResult,
)

logger = logging.getLogger(__name__)


class OrmArchiveFindingCardsRepository(ArchiveFindingCardsPort):
    def archive_finding_cards(self, *, command: ArchiveFindingCardsCommand) -> ArchiveFindingCardsResult:
        from django.db.models import Q

        from components.project.domain.errors import TaskValidationError
        from components.recycle_bin.application.commands.trash_command import TrashCommand
        from components.recycle_bin.application.providers.recycle_bin_provider import (
            get_recycle_bin_service,
        )
        from components.shared_kernel.domain.errors import ConflictError
        from infrastructure.persistence.project.models import Task

        if command.archived_by is None:
            raise TaskValidationError("ArchiveFindingCardsCommand.archived_by is required (recycle-bin attribution).")

        # The card ↔ finding link stamped at birth by the finding→board pipeline:
        # ``metadata.payload.finding_id`` (SSOT uuid) with ``lookup_key`` (= the
        # fingerprint) as the pre-stamping fallback. Empty keys never match-all.
        lookup = Q()
        if command.finding_id:
            lookup |= Q(metadata__payload__finding_id=str(command.finding_id))
        if command.fingerprint:
            lookup |= Q(metadata__payload__lookup_key=command.fingerprint)
        if not lookup:
            return ArchiveFindingCardsResult(archived_task_ids=(), already_archived=0)

        tasks = list(
            Task.objects.filter(workspace_id=command.workspace_id)
            .filter(lookup)
            .exclude(status=Task.ARCHIVED)  # idempotent: the bin round-trip is one-way here
            .select_related("column")
        )
        if not tasks:
            return ArchiveFindingCardsResult(archived_task_ids=(), already_archived=0)

        detail = (command.detail or "").strip()
        why = f"finding suppressed ({detail})" if detail else "finding suppressed"
        archived_at = datetime.now(UTC).isoformat()
        service = get_recycle_bin_service()

        archived: list[str] = []
        already = 0
        for task in tasks:
            self._stamp_provenance_and_comment(task, command=command, why=why, at=archived_at)
            try:
                service.trash(
                    TrashCommand(
                        workspace_id=command.workspace_id,
                        entity_type="task",
                        entity_id=str(task.id),
                        deleted_by=command.archived_by,
                        reason=f"auto-archived: {why}",
                    )
                )
            except ConflictError:
                # Already in the bin (race with a concurrent suppress/delete) —
                # the outcome asked for already holds.
                already += 1
                continue
            archived.append(str(task.id))
            logger.info(
                "finding_card_archived workspace_id=%s task_id=%s finding_id=%s reason=%s",
                command.workspace_id,
                task.id,
                command.finding_id or command.fingerprint,
                command.reason,
            )
        return ArchiveFindingCardsResult(archived_task_ids=tuple(archived), already_archived=already)

    @staticmethod
    def _stamp_provenance_and_comment(task, *, command: ArchiveFindingCardsCommand, why: str, at: str) -> None:
        """Append the provenance event + card comment BEFORE the trash.

        Same growable ``metadata.provenance`` shape as ``_finding_processing`` /
        ``open_draft_pr`` / ``resolve_finding_task``; the comment uses the real
        TaskComment row so the card's history reads the archive cause after a
        restore. Comment attribution = the workspace's AI teammate user.
        """
        from infrastructure.persistence.project.models import TaskComment
        from infrastructure.persistence.users.models import CustomUser

        meta = task.metadata or {}
        provenance = meta.get("provenance") or {"events": []}
        provenance.setdefault("events", [])
        provenance["events"].append(
            {
                "actor": command.actor_label,
                "action": f"card auto-archived to recycle bin — {why}",
                "at": at,
            }
        )
        provenance["last_handled_by"] = command.actor_label
        provenance["last_handled_at"] = at
        meta["provenance"] = provenance
        task.metadata = meta
        task.save(update_fields=["metadata", "updated_at"])

        author = CustomUser.objects.filter(id=command.archived_by).first()
        if author is not None:
            TaskComment.objects.create(
                task=task,
                author=author,
                comment=(
                    f"🗄️ Card auto-archived to the recycle bin — {why}. "
                    "The finding record is retained (suppressed) in the findings panel; "
                    "restore this card from the board's RECYCLE BIN tray if needed."
                ),
            )

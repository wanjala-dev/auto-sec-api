"""FindingResolved → auto-archive the suppressed finding's board card.

Henry's ruling (2026-08-09): when a finding is SUPPRESSED (accepted risk /
false positive / demo noise), its board card is intake noise and auto-archives
off the Suggested lane — a recycle-bin tombstone (restorable from the board's
RECYCLE BIN tray), never a delete. The finding row itself is the SSOT and is
untouched; the card is the *local copy* (ADR 0004 C7) being tidied.

Scope decisions, named:

- **Suppressed only.** ``FindingResolved`` also fires with ``reason="resolved"``
  (operator resolve) and reconciler reasons ("remediated"/"no_longer_observed").
  The teams/boards report recommended archiving resolved/stale cards too, but a
  RESOLVED card is proof-of-work the remediation capture loop reads
  (``BoardFindingFactsRepository``) — auto-archiving those is a separate product
  decision, left as an open follow-up. This handler filters ``reason ==
  "suppressed"`` and nothing else.
- **Un-suppress (reopen) does NOT auto-restore the card.** There is no
  ``FindingReopened`` event, and silently resurrecting a card the operator may
  have re-triaged is not obviously right — the RECYCLE BIN tray restore is one
  click and lossless (``pre_trash_status``). Revisit if operators ask.

The write itself goes through the project context's application surface
(``ArchiveFindingCardsUseCase``) — the project context owns the Task (C2); this
handler only reacts to the shared-kernel event, resolves the AI identity for
attribution, and enriches the provenance with the operator's suppress reason.
"""

from __future__ import annotations

import logging

from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingResolved

logger = logging.getLogger(__name__)

#: The FindingResolved.reason token this handler acts on.
SUPPRESSED_REASON = "suppressed"


@subscribes_to(FindingResolved)
def handle_finding_resolved_board(event: FindingResolved) -> None:
    if (event.reason or "") != SUPPRESSED_REASON:
        return  # resolved/remediated/no_longer_observed cards stay (see module docstring)

    from components.agents.application.providers.agent_permissions_provider import (
        get_agent_permissions_provider,
    )
    from components.agents.application.providers.ai_provider import AIProvider
    from components.findings.application.providers.finding_provider import FindingProvider
    from components.project.application.ports.archive_finding_cards_port import (
        ArchiveFindingCardsCommand,
    )
    from components.project.application.providers.project_provider import ProjectProvider

    workspace = AIProvider.build_workspace_query().get_by_id(event.workspace_id)
    if workspace is None:
        logger.warning(
            "finding_resolved_board_workspace_missing workspace_id=%s finding_id=%s",
            event.workspace_id,
            event.finding_id,
        )
        return

    # The operator's risk-acceptance "why" (status_reason) enriches the card's
    # provenance comment. Best-effort — a missing finding (e.g. the derived-uuid
    # emission path) still archives by fingerprint with the coarse reason.
    detail = ""
    try:
        finding = FindingProvider.build_finding_store().find_by_id(event.workspace_id, event.finding_id)
        if finding is not None:
            detail = finding.status_reason or ""
    except Exception:
        logger.exception(
            "finding_resolved_board_detail_read_failed workspace_id=%s finding_id=%s",
            event.workspace_id,
            event.finding_id,
        )

    try:
        _profile, ai_user = get_agent_permissions_provider().ensure_ai_identity(workspace)
        result = ProjectProvider.build_archive_finding_cards_use_case().execute(
            command=ArchiveFindingCardsCommand(
                workspace_id=event.workspace_id,
                finding_id=str(event.finding_id),
                fingerprint=event.fingerprint or "",
                reason=SUPPRESSED_REASON,
                detail=detail,
                archived_by=ai_user.id,
                actor_label="system:finding_suppressed",
            )
        )
    except Exception:
        logger.exception(
            "finding_resolved_board_archive_failed workspace_id=%s finding_id=%s",
            event.workspace_id,
            event.finding_id,
        )
        return

    logger.info(
        "finding_resolved_board_archived workspace_id=%s finding_id=%s archived=%s already_archived=%s",
        event.workspace_id,
        event.finding_id,
        result.archived_count,
        result.already_archived,
    )

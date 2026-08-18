"""Project the pending-sign-off queue onto the AI-team Kanban board.

Phase 6b of the sign-off track. Each pending sign-off item (from the
Phase-6a queue) is materialized as a **Task on the workspace's
auto-generated Agents "AI Findings" board**, assigned to the workspace
owner, carrying the receipts + risk band + artifact ref in
``metadata.context``. This unifies the sign-off queue with the existing
AI-findings Kanban so the owner reviews everything in one place.

The artifact's ``review_state`` (owned by each context's SignOffPort
adapter) stays the single source of truth; the task is a *projection*
kept in sync by this materializer:

* **Upsert** — for every currently-pending item, create (idempotently,
  via ``persist_finding_as_task``) a card on the canonical "Todo" intake lane,
  assigned to ``workspace.workspace_owner``.
* **Reconcile** — for every existing ``ai.sign_off_pending`` task whose
  artifact is NO LONGER pending, move it to the terminal column that
  matches the artifact's final review state (approved → "Complete",
  rejected → "Canceled"; ADR 0030 D2 canonical lanes) and stamp the task
  status. Idempotent: a task
  already in the right column is left untouched.

Approve/Reject already exist (Phase-6a ``SignOffQueueService`` + the
``/sign-off/.../approve|reject/`` endpoints do the real send/publish).
This materializer does NOT duplicate them — when a user approves via the
sign-off endpoint the artifact leaves the pending set, and the next
materializer cycle moves its task. The periodic reconcile is the safety
net.

Architecture note: this is a sign-off *application service* and stays
ORM-free. Reuse is the rule — it calls the sanctioned agents entry
points (``ensure_agents_board``, ``persist_finding_as_task``), the kernel
query (``list_pending_sign_offs``) + registry (``get_state``), and — for
the reconcile move — ``project``'s own ``UpdateTaskUseCase`` (via
``ProjectProvider``), which sets the terminal column + status stamp in a
single sanctioned call (same-board column move + status). The three
cross-context READS it needs (the ``Workspace`` row, the AI-agents
workspace ids, and the existing sign-off ``Task`` rows) go through the
sign-off-owned :class:`SignOffBoardPort` (ORM adapter in
``infrastructure/adapters/``), so this service never imports another
context's persistence models or infrastructure adapters.
"""

from __future__ import annotations

import logging

from components.sign_off.application.ports.sign_off_board_port import (
    SignOffBoardPort,
    SignOffTaskRef,
)
from components.sign_off.application.providers.sign_off_board_provider import (
    get_sign_off_board_port,
)
from components.sign_off.application.providers.sign_off_registry_provider import (
    SignOffRegistry,
    get_sign_off_registry,
)
from components.sign_off.application.services.sign_off_queue_query import (
    list_pending_sign_offs,
)
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.risk_band import RiskBand
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem

logger = logging.getLogger(__name__)

# Provenance label carried on every materialized sign-off task. Distinct
# from the specialist/detector labels so the reconcile query can find
# exactly the tasks this materializer owns.
SIGN_OFF_SOURCE_TYPE = "ai.sign_off_pending"
AGENT_TYPE = "sign_off_reviewer"
DETECTOR_KEY = "sign_off_queue"

# Terminal task statuses mirrored from ``project.Task`` (DONE / ARCHIVED).
# Kept as string literals so this application service never imports the
# ``project`` ORM — the update is applied via ``UpdateTaskUseCase``, whose
# serializer validates these against ``Task.CHOICES_STATUS``.
_STATUS_DONE = "done"
_STATUS_ARCHIVED = "archived"

# Risk band → 0-100 impact score. RED items sort to the top of the board.
_BAND_IMPACT: dict[RiskBand, int] = {
    RiskBand.RED: 80,
    RiskBand.AMBER: 45,
    RiskBand.GREEN: 20,
}


def _idempotency_key(artifact_type: str, artifact_id: str) -> str:
    return f"signoff:{artifact_type}:{artifact_id}"


def _receipts_summary_dict(item: SignOffItem) -> dict:
    s = item.receipts_summary
    return {
        "unverified_figures": s.unverified_figures,
        "ungrounded_claims": s.ungrounded_claims,
        "voice_flags": s.voice_flags,
        "is_clean": s.is_clean,
    }


def _finding_copy(item: SignOffItem) -> tuple[str, str]:
    """Build the card title + narrative for a pending sign-off item."""
    title_label = (item.title or "").strip() or f"{item.artifact_type} {item.artifact_id}"
    title = f"Review: {title_label}"
    s = item.receipts_summary
    if s.is_clean:
        flags = "no verification flags"
    else:
        parts = []
        if s.unverified_figures:
            parts.append(f"{s.unverified_figures} unverified figure(s)")
        if s.ungrounded_claims:
            parts.append(f"{s.ungrounded_claims} ungrounded claim(s)")
        if s.voice_flags:
            parts.append(f"{s.voice_flags} voice flag(s)")
        flags = ", ".join(parts) if parts else "flags present"
    summary = (
        f"A {item.artifact_type} is awaiting your sign-off before it can be "
        f"sent to {item.audience or 'its audience'}. Risk band: "
        f"{item.risk_band.value.upper()} ({flags}). Review the receipts and "
        f"approve, request changes, or reject from the sign-off queue."
    )
    return title, summary


def materialize_workspace_signoff_tasks(
    workspace_id: str,
    *,
    registry: SignOffRegistry | None = None,
    board_port: SignOffBoardPort | None = None,
) -> dict[str, int]:
    """Sync one workspace's pending-sign-off queue onto its Agents board.

    Returns a counts dict: ``created`` (new cards upserted this run —
    idempotent replays are not counted), ``reconciled_accepted``,
    ``reconciled_dismissed``, and ``reconcile_skipped``.
    """
    from components.agents.application.facades.ai_teammate_facade import (
        TODO,
        ensure_agents_board,
    )
    from components.agents.application.handlers.specialist_persistence_service import (
        persist_finding_as_task,
    )

    registry = registry or get_sign_off_registry()
    board_port = board_port or get_sign_off_board_port()

    workspace = board_port.get_workspace(workspace_id)
    if workspace is None:
        logger.warning("signoff_materialize_workspace_missing workspace_id=%s", workspace_id)
        return {
            "created": 0,
            "reconciled_accepted": 0,
            "reconciled_dismissed": 0,
            "reconcile_skipped": 0,
        }

    board = ensure_agents_board(workspace)
    intake_column = board.column(TODO)
    ai_user_id = str(board.team.created_by_id)
    owner_id = str(workspace.workspace_owner_id) if workspace.workspace_owner_id else None

    pending = list_pending_sign_offs(str(workspace_id), registry=registry)
    pending_refs: set[tuple[str, str]] = {(item.artifact_type, str(item.artifact_id)) for item in pending}

    # ── Upsert: pending item → Todo-lane (intake) card ──────────────────
    created = 0
    for item in pending:
        title, summary = _finding_copy(item)
        finding_context = {
            "artifact_type": item.artifact_type,
            "artifact_id": str(item.artifact_id),
            "risk_band": item.risk_band.value,
            "review_state": item.review_state.value,
            "receipts_summary": _receipts_summary_dict(item),
            "audience": item.audience,
        }
        try:
            task_id = persist_finding_as_task(
                workspace=workspace,
                intake_column=intake_column,
                ai_user_id=ai_user_id,
                title=title,
                summary=summary,
                source_type=SIGN_OFF_SOURCE_TYPE,
                agent_type=AGENT_TYPE,
                detector_key=DETECTOR_KEY,
                payload_data={
                    "artifact_type": item.artifact_type,
                    "artifact_id": str(item.artifact_id),
                },
                context=finding_context,
                impact_score=_BAND_IMPACT.get(item.risk_band, 20),
                idempotency_key=_idempotency_key(item.artifact_type, str(item.artifact_id)),
                assignee_ids=[owner_id] if owner_id else None,
            )
        except Exception:
            # One bad item must not blank the rest of this workspace's sweep.
            logger.exception(
                "signoff_materialize_upsert_failed workspace_id=%s artifact_type=%s artifact_id=%s",
                workspace_id,
                item.artifact_type,
                item.artifact_id,
            )
            continue
        if task_id is not None:
            created += 1

    # ── Reconcile: no-longer-pending task → terminal column ─────────────
    reconciled = _reconcile_terminal_tasks(
        workspace_id=str(workspace_id),
        board=board,
        registry=registry,
        board_port=board_port,
        pending_refs=pending_refs,
        ai_user_id=ai_user_id,
    )

    result = {"created": created, **reconciled}
    logger.info(
        "signoff_materialize_workspace_done workspace_id=%s created=%s "
        "reconciled_accepted=%s reconciled_dismissed=%s reconcile_skipped=%s",
        workspace_id,
        created,
        result["reconciled_accepted"],
        result["reconciled_dismissed"],
        result["reconcile_skipped"],
    )
    return result


def _reconcile_terminal_tasks(
    *,
    workspace_id: str,
    board,
    registry: SignOffRegistry,
    board_port: SignOffBoardPort,
    pending_refs: set[tuple[str, str]],
    ai_user_id: str,
) -> dict[str, int]:
    """Move sign-off tasks whose artifact left the pending set to a terminal
    column matching the artifact's final review state. Idempotent.

    The move + status stamp go through ``project``'s ``UpdateTaskUseCase`` —
    a same-board column move (Todo → Complete/Canceled on this workspace's
    own Agents board) plus the terminal status — so the sign-off service never
    writes ``project.Task`` directly. Existing tasks are read through the
    sign-off board port. The AI user (the Agents team's creator, ``ai_user_id``)
    is the actor, so the use case's membership check passes.
    """
    from components.agents.application.facades.ai_teammate_facade import (
        CANCELED,
        COMPLETE,
    )
    from components.project.application.ports.update_task_port import UpdateTaskCommand
    from components.project.application.providers.project_provider import ProjectProvider

    accepted_col = board.column(COMPLETE)
    dismissed_col = board.column(CANCELED)
    update_task = ProjectProvider.build_update_task_use_case()

    reconciled_accepted = 0
    reconciled_dismissed = 0
    reconcile_skipped = 0

    existing: list[SignOffTaskRef] = board_port.list_signoff_tasks(
        workspace_id=workspace_id,
        source_type=SIGN_OFF_SOURCE_TYPE,
    )

    for task in existing:
        artifact_type = task.artifact_type
        artifact_id = task.artifact_id
        if not artifact_type or not artifact_id:
            reconcile_skipped += 1
            continue

        # Still pending → leave the card where it is.
        if (artifact_type, str(artifact_id)) in pending_refs:
            continue

        try:
            state = registry.get_adapter(artifact_type).get_state(str(artifact_id))
        except Exception:
            # Artifact deleted / adapter error — don't thrash the card.
            logger.exception(
                "signoff_reconcile_state_lookup_failed workspace_id=%s artifact_type=%s artifact_id=%s",
                workspace_id,
                artifact_type,
                artifact_id,
            )
            reconcile_skipped += 1
            continue

        if state == ReviewState.APPROVED:
            target_col, target_status = accepted_col, _STATUS_DONE
        elif state == ReviewState.REJECTED:
            target_col, target_status = dismissed_col, _STATUS_ARCHIVED
        else:
            # PENDING / CHANGES_REQUESTED but not in the pending set (e.g.
            # a transient adapter hiccup during list_pending). Leave it.
            reconcile_skipped += 1
            continue

        # Idempotent: already in the right column + status → no write.
        if task.column_id == str(target_col.id) and task.status == target_status:
            continue

        try:
            update_task.execute(
                command=UpdateTaskCommand(
                    task_id=task.task_id,
                    user_id=ai_user_id,
                    data={"column": str(target_col.id), "status": target_status},
                )
            )
        except Exception:
            # One bad card must not blank the rest of this workspace's sweep.
            logger.exception(
                "signoff_reconcile_move_failed workspace_id=%s task_id=%s artifact_type=%s artifact_id=%s",
                workspace_id,
                task.task_id,
                artifact_type,
                artifact_id,
            )
            reconcile_skipped += 1
            continue

        if state == ReviewState.APPROVED:
            reconciled_accepted += 1
        else:
            reconciled_dismissed += 1
        logger.info(
            "signoff_reconcile_task_moved workspace_id=%s task_id=%s artifact_type=%s artifact_id=%s state=%s",
            workspace_id,
            task.task_id,
            artifact_type,
            artifact_id,
            state.value,
        )

    return {
        "reconciled_accepted": reconciled_accepted,
        "reconciled_dismissed": reconciled_dismissed,
        "reconcile_skipped": reconcile_skipped,
    }


def materialize_all_pending_signoff_tasks(
    *,
    registry: SignOffRegistry | None = None,
    board_port: SignOffBoardPort | None = None,
) -> dict[str, int]:
    """Sweep every workspace that has an Agents team, materializing its
    pending-sign-off queue onto the board.

    Per-workspace failures are caught and logged — one broken workspace
    never halts the sweep (the one legitimate log-and-continue).
    """
    registry = registry or get_sign_off_registry()
    board_port = board_port or get_sign_off_board_port()

    totals = {
        "workspaces": 0,
        "created": 0,
        "reconciled_accepted": 0,
        "reconciled_dismissed": 0,
        "reconcile_skipped": 0,
        "errors": 0,
    }

    for workspace_id in board_port.list_agents_workspace_ids():
        if workspace_id is None:
            continue
        totals["workspaces"] += 1
        try:
            result = materialize_workspace_signoff_tasks(str(workspace_id), registry=registry, board_port=board_port)
        except Exception:
            totals["errors"] += 1
            logger.exception(
                "signoff_materialize_workspace_failed workspace_id=%s",
                workspace_id,
            )
            continue
        totals["created"] += result["created"]
        totals["reconciled_accepted"] += result["reconciled_accepted"]
        totals["reconciled_dismissed"] += result["reconciled_dismissed"]
        totals["reconcile_skipped"] += result["reconcile_skipped"]

    logger.info(
        "signoff_materialize_sweep_done workspaces=%s created=%s "
        "reconciled_accepted=%s reconciled_dismissed=%s reconcile_skipped=%s "
        "errors=%s",
        totals["workspaces"],
        totals["created"],
        totals["reconciled_accepted"],
        totals["reconciled_dismissed"],
        totals["reconcile_skipped"],
        totals["errors"],
    )
    return totals

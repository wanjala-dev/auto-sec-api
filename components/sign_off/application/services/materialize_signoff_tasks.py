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
  via ``persist_finding_as_task``) a card on the "Suggested" column,
  assigned to ``workspace.workspace_owner``.
* **Reconcile** — for every existing ``ai.sign_off_pending`` task whose
  artifact is NO LONGER pending, move it to the terminal column that
  matches the artifact's final review state (approved → "Accepted",
  rejected → "Dismissed") and stamp the task status. Idempotent: a task
  already in the right column is left untouched.

Approve/Reject already exist (Phase-6a ``SignOffQueueService`` + the
``/sign-off/.../approve|reject/`` endpoints do the real send/publish).
This materializer does NOT duplicate them — when a user approves via the
sign-off endpoint the artifact leaves the pending set, and the next
materializer cycle moves its task. The periodic reconcile is the safety
net.

Architecture note: this is a sign-off *application service*. Reuse is the
rule — it calls the sanctioned agents entry points
(``ensure_agents_board``, ``persist_finding_as_task``) and the kernel
query (``list_pending_sign_offs``) + registry (``get_state``). It reads
the ``project.Task`` ORM directly for the reconcile move (there is no
sanctioned "move task" use case to reuse); ORM access from the agents
application layer is the established pattern here (see
``components/agents/application/services/detector_cycle.py``). It never
imports another context's *infrastructure adapters*.
"""

from __future__ import annotations

import logging

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
) -> dict[str, int]:
    """Sync one workspace's pending-sign-off queue onto its Agents board.

    Returns a counts dict: ``created`` (new cards upserted this run —
    idempotent replays are not counted), ``reconciled_accepted``,
    ``reconciled_dismissed``, and ``reconcile_skipped``.
    """
    from infrastructure.persistence.workspaces.models import Workspace

    from components.agents.application.facades.ai_teammate_facade import (
        SUGGESTED,
        ensure_agents_board,
    )
    from components.agents.application.handlers.specialist_persistence_service import (
        persist_finding_as_task,
    )

    registry = registry or get_sign_off_registry()

    workspace = Workspace.objects.filter(id=workspace_id).first()
    if workspace is None:
        logger.warning(
            "signoff_materialize_workspace_missing workspace_id=%s", workspace_id
        )
        return {
            "created": 0,
            "reconciled_accepted": 0,
            "reconciled_dismissed": 0,
            "reconcile_skipped": 0,
        }

    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)
    owner_id = str(workspace.workspace_owner_id) if workspace.workspace_owner_id else None

    pending = list_pending_sign_offs(str(workspace_id), registry=registry)
    pending_refs: set[tuple[str, str]] = {
        (item.artifact_type, str(item.artifact_id)) for item in pending
    }

    # ── Upsert: pending item → Suggested-column card ────────────────────
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
                suggested_column=suggested_column,
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
                "signoff_materialize_upsert_failed workspace_id=%s "
                "artifact_type=%s artifact_id=%s",
                workspace_id, item.artifact_type, item.artifact_id,
            )
            continue
        if task_id is not None:
            created += 1

    # ── Reconcile: no-longer-pending task → terminal column ─────────────
    reconciled = _reconcile_terminal_tasks(
        workspace_id=str(workspace_id),
        board=board,
        registry=registry,
        pending_refs=pending_refs,
    )

    result = {"created": created, **reconciled}
    logger.info(
        "signoff_materialize_workspace_done workspace_id=%s created=%s "
        "reconciled_accepted=%s reconciled_dismissed=%s reconcile_skipped=%s",
        workspace_id, created, result["reconciled_accepted"],
        result["reconciled_dismissed"], result["reconcile_skipped"],
    )
    return result


def _reconcile_terminal_tasks(
    *,
    workspace_id: str,
    board,
    registry: SignOffRegistry,
    pending_refs: set[tuple[str, str]],
) -> dict[str, int]:
    """Move sign-off tasks whose artifact left the pending set to a terminal
    column matching the artifact's final review state. Idempotent."""
    from infrastructure.persistence.project.models import Task

    from components.agents.application.facades.ai_teammate_facade import (
        ACCEPTED,
        DISMISSED,
    )

    accepted_col = board.column(ACCEPTED)
    dismissed_col = board.column(DISMISSED)

    reconciled_accepted = 0
    reconciled_dismissed = 0
    reconcile_skipped = 0

    existing = Task.objects.filter(
        workspace_id=workspace_id,
        source_type=SIGN_OFF_SOURCE_TYPE,
    ).select_related("column")

    for task in existing.iterator(chunk_size=500):
        context = (task.metadata or {}).get("context") or {}
        artifact_type = context.get("artifact_type")
        artifact_id = context.get("artifact_id")
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
                "signoff_reconcile_state_lookup_failed workspace_id=%s "
                "artifact_type=%s artifact_id=%s",
                workspace_id, artifact_type, artifact_id,
            )
            reconcile_skipped += 1
            continue

        if state == ReviewState.APPROVED:
            target_col, target_status = accepted_col, Task.DONE
        elif state == ReviewState.REJECTED:
            target_col, target_status = dismissed_col, Task.ARCHIVED
        else:
            # PENDING / CHANGES_REQUESTED but not in the pending set (e.g.
            # a transient adapter hiccup during list_pending). Leave it.
            reconcile_skipped += 1
            continue

        # Idempotent: already in the right column → no write.
        if task.column_id == target_col.id and task.status == target_status:
            continue

        task.column = target_col
        task.status = target_status
        task.save(update_fields=["column", "status", "updated_at"])
        if state == ReviewState.APPROVED:
            reconciled_accepted += 1
        else:
            reconciled_dismissed += 1
        logger.info(
            "signoff_reconcile_task_moved workspace_id=%s task_id=%s "
            "artifact_type=%s artifact_id=%s state=%s",
            workspace_id, task.id, artifact_type, artifact_id, state.value,
        )

    return {
        "reconciled_accepted": reconciled_accepted,
        "reconciled_dismissed": reconciled_dismissed,
        "reconcile_skipped": reconcile_skipped,
    }


def materialize_all_pending_signoff_tasks(
    *,
    registry: SignOffRegistry | None = None,
) -> dict[str, int]:
    """Sweep every workspace that has an Agents team, materializing its
    pending-sign-off queue onto the board.

    Per-workspace failures are caught and logged — one broken workspace
    never halts the sweep (the one legitimate log-and-continue).
    """
    from infrastructure.persistence.team.models import Team

    registry = registry or get_sign_off_registry()

    totals = {
        "workspaces": 0,
        "created": 0,
        "reconciled_accepted": 0,
        "reconciled_dismissed": 0,
        "reconcile_skipped": 0,
        "errors": 0,
    }

    workspace_ids = (
        Team.objects.filter(kind=Team.Kind.AI_AGENTS, status=Team.ACTIVE)
        .values_list("workspace_id", flat=True)
        .distinct()
    )
    for workspace_id in workspace_ids.iterator(chunk_size=500):
        if workspace_id is None:
            continue
        totals["workspaces"] += 1
        try:
            result = materialize_workspace_signoff_tasks(
                str(workspace_id), registry=registry
            )
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
        totals["workspaces"], totals["created"], totals["reconciled_accepted"],
        totals["reconciled_dismissed"], totals["reconcile_skipped"], totals["errors"],
    )
    return totals

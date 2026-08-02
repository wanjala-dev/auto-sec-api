"""Resolve an ai.* board finding — the owning-context transition (ADR 0012 P4a).

The agents context OWNS the triage lifecycle of the board findings it files
(``persist_finding_as_task`` creates them via the project application surface;
``_finding_processing.process_pending_finding`` flips them ``pending`` →
``triaged`` under a row lock and appends provenance). Until now nothing moved a
finding past ``triaged`` — the "resolved" transition this function adds is the
clean next step in that same lifecycle, in the same context that owns it.

It is an APPLICATION surface (a front door) so *other* contexts — the Remediation
Memory reconciler in particular — can request a resolve WITHOUT reaching into the
board themselves (Explicit Architecture C2: a component never writes data it does
not own). The reconciler verifies a fix's PR merged, then calls this to transition
the finding — the write stays here, in the owner.

Mirrors ``process_pending_finding``'s discipline: a ``select_for_update`` row
lock, an idempotent re-check (already-resolved ⇒ no-op, no duplicate provenance),
and a growable ``provenance.events`` append. Workspace-scoped: a task from another
workspace is never touched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from components.shared_kernel.application.transactional import atomic

logger = logging.getLogger(__name__)

_RESOLVER = "remediation_reconciler"


def resolve_board_finding(*, workspace_id: str, finding_task_id: str, reason: str) -> bool:
    """Transition an ai.* board finding to ``resolved`` + append provenance.

    Returns ``True`` if this call performed the transition, ``False`` if the
    finding was already resolved or does not exist (idempotent). The ``project``
    context owns the ``Task`` row; the agents context owns this finding's triage
    lifecycle and drives its ``metadata`` — the same segregated local-copy pattern
    ``_finding_processing`` already uses.

    Framework-free application surface: the transaction boundary comes from the
    shared-kernel ``atomic`` helper (not a direct ``django.db`` import), and the
    row lock is expressed on the ORM manager — keeping this within the
    application-purity fitness rule while still holding a real lock.
    """
    from infrastructure.persistence.project.models import Task

    try:
        with atomic():
            task = (
                Task.objects.select_for_update(of=("self",))
                .filter(id=finding_task_id, workspace_id=workspace_id)
                .first()
            )
            if task is None:
                return False

            meta = task.metadata or {}
            triage = meta.get("triage") or {}
            if str(triage.get("status", "")).lower() == "resolved":
                return False  # already resolved — idempotent no-op

            now = datetime.now(UTC).isoformat()
            triage["status"] = "resolved"
            triage["resolved_at"] = now
            meta["triage"] = triage

            provenance = meta.get("provenance") or {"events": []}
            provenance.setdefault("events", [])
            provenance["events"].append(
                {
                    "actor": f"agent:{_RESOLVER}",
                    "action": f"finding resolved: {reason}",
                    "at": now,
                }
            )
            provenance["last_handled_by"] = _RESOLVER
            provenance["last_handled_at"] = now
            meta["provenance"] = provenance

            task.metadata = meta
            task.save(update_fields=["metadata", "updated_at"])
    except (ValueError, TypeError):
        # Malformed id (Task pks are integers) — same answer as absent.
        return False

    logger.info(
        "board_finding_resolved workspace_id=%s finding_task_id=%s reason=%s",
        workspace_id,
        finding_task_id,
        reason,
    )
    return True

"""Resolving the autonomy a run executes under — ONE site (ADR 0035 D5).

Two things need this answer: the tool gate, which enforces it per call, and the
run row, which records it for whoever asks later what the run was permitted to
do. They must never disagree.

That is not a hypothetical worry. ``_stamp_autonomy_mode`` in ``base.py`` already
says why:

    "a second resolution site could disagree with the gate, and then the audit
     trail would describe a policy that was never applied."

So neither caller computes the mode itself. Both call :func:`resolve_run_mode`
with the same three inputs, and the mapping from those inputs to a mode lives
once more in ``autonomy_mode.resolve``. A drift test pins the agreement.

**A failed workspace read becomes UNKNOWN, deliberately.** Not ``None`` and not
a default. UNKNOWN holds writes at the gate and reads as "we do not know" on the
row — the honest answer in both places. Defaulting to ASSIST would fail open on
the control whose entire job is answering "may the AI change things in my
account", and would additionally write a governance claim we cannot support.
"""

from __future__ import annotations

import logging

from components.agents.domain.value_objects.autonomy_mode import AutonomyMode, parse, resolve

logger = logging.getLogger(__name__)


def read_workspace_mode(workspace_id) -> AutonomyMode | None:
    """The workspace's configured mode.

    ``None`` when there is no workspace to govern — a run with nothing to
    govern is not the same as a run whose policy we failed to read, and the
    caller needs to tell them apart.

    :class:`AutonomyMode.UNKNOWN` when the read itself failed.
    """
    if not workspace_id:
        return None

    try:
        from components.agents.infrastructure.adapters.workspace_autonomy_adapter import (
            WorkspaceAutonomyAdapter,
        )

        stored = WorkspaceAutonomyAdapter().get_mode(workspace_id=str(workspace_id))
    except Exception:
        logger.exception(
            "autonomy_mode read failed workspace_id=%s — treating as UNKNOWN (writes held)",
            workspace_id,
        )
        return AutonomyMode.UNKNOWN

    return None if stored is None else parse(stored)


def resolve_run_mode(*, execution_mode, user_id, workspace_id) -> AutonomyMode:
    """The mode a run executes under, from the three signals that decide it.

    Called by the gate (per run, cached on the agent) and by the runner (once,
    to stamp the row). Same inputs, same function, same answer.
    """
    from components.agents.infrastructure.adapters.langchain.base import is_ai_service_principal

    try:
        is_autonomous = is_ai_service_principal(user_id, workspace_id)
    except Exception:
        # The safe direction: an unresolvable principal is not treated as a
        # service principal, matching the gate's existing fallback.
        logger.exception("service-principal lookup failed user_id=%s workspace_id=%s", user_id, workspace_id)
        is_autonomous = False

    return resolve(
        execution_mode=execution_mode,
        is_autonomous=is_autonomous,
        workspace_mode=read_workspace_mode(workspace_id),
    )


__all__ = ["read_workspace_mode", "resolve_run_mode"]

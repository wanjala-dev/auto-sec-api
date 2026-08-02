"""Port: resolve a finding board-task to a terminal state (ADR 0012 P4a).

The board ``Task`` is owned by the ``project`` context, and a finding's lifecycle
state (``metadata.triage.status``) lives on that Task. Per the architecture skill
C2 ("a component never changes data it does not own"), no other context may flip a
finding to *resolved* by writing the Task directly — they route through this
application surface, which the project context implements over its own persistence.

This is deliberately a thin, single-purpose port: mark a finding-task resolved,
stamp who/what/why into the growable provenance trail, and (best-effort) emit the
shared-kernel ``FindingResolved`` event so other lenses can react. It is idempotent
— resolving an already-resolved task is a no-op that reports ``already_resolved``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolveFindingTaskCommand:
    workspace_id: str
    task_id: str
    # A coarse token recorded on the finding + carried on the FindingResolved event,
    # e.g. "remediated" (its draft PR merged) — mirrors FindingResolved.reason.
    reason: str = "remediated"
    # Attribution for the provenance event (who/what resolved it).
    resolved_by: str = ""


@dataclass(frozen=True)
class ResolveFindingTaskResult:
    task_id: str
    resolved: bool  # True if now resolved (this call or already)
    already_resolved: bool  # True if it was resolved before this call (idempotent hit)
    found: bool  # False if the task does not exist in the workspace


class ResolveFindingTaskPort(abc.ABC):
    """Secondary port for marking a finding board-task resolved (owner-write)."""

    @abc.abstractmethod
    def resolve_finding_task(self, *, command: ResolveFindingTaskCommand) -> ResolveFindingTaskResult:
        """Flip the finding-task to resolved in its own workspace.

        Workspace-scoped: a task id from another workspace resolves to
        ``found=False`` and writes nothing (tenant isolation). Idempotent: an
        already-resolved task returns ``already_resolved=True`` without a second
        write or a duplicate event.
        """
        ...

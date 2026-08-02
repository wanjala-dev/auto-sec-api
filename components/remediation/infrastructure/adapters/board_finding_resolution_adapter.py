"""Adapter: transition a finding to RESOLVED via the OWNING context (ADR 0012 P4a).

Implements :class:`FindingResolutionPort`. It does NOT write ``project.Task``
itself — that would violate Explicit Architecture C2 ("a component never changes
data it does not own"). Instead it delegates to the ``agents`` context's
application surface (``resolve_board_finding``), which owns the ai.* board
finding's triage lifecycle (it files the finding via ``persist_finding_as_task``
and flips ``pending`` → ``triaged`` in ``_finding_processing``). The
``resolved`` transition lives there, in the owner; remediation only *requests* it
through a permitted cross-context call into another context's application layer
(C3) — never its infrastructure, never the ``project.Task`` model.

The owning function is idempotent + workspace-scoped (already-resolved ⇒ no-op,
another workspace's task untouched), so this adapter is too.
"""

from __future__ import annotations

from components.remediation.application.ports.finding_resolution_port import (
    FindingResolutionPort,
)


class BoardFindingResolutionAdapter(FindingResolutionPort):
    def mark_resolved(self, *, workspace_id: str, finding_task_id: str, reason: str) -> bool:
        from components.agents.application.services.resolve_board_finding import (
            resolve_board_finding,
        )

        return resolve_board_finding(
            workspace_id=workspace_id,
            finding_task_id=finding_task_id,
            reason=reason,
        )

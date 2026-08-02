"""Port: transition a finding/board task to RESOLVED (ADR 0012 P4a).

P3's review found the board triage status never moves past ``"triaged"`` — so
the gate's "finding resolved" leg could never become true automatically. This
port is the clean domain transition that closes that gap: when the reconciler
has verified a fix's PR merged, it marks the finding resolved and stamps a
provenance event, mirroring how ``open_draft_pr``'s ``_record_on_finding``
appends provenance.

It is a WRITE onto the board (``project.Task``), so it lives behind a port the
remediation context owns; the infrastructure adapter performs the mutation
(architecture skill C7: the board Task is a local work-item — updating its
triage state is legitimate). Idempotent: a finding already resolved is a no-op.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class FindingResolutionPort(ABC):
    @abstractmethod
    def mark_resolved(self, *, workspace_id: str, finding_task_id: str, reason: str) -> bool:
        """Transition the finding to ``resolved`` and append a provenance event.

        Returns ``True`` if this call performed the transition, ``False`` if the
        finding was already resolved or does not exist (idempotent — safe to call
        repeatedly). Always workspace-scoped: a task from another workspace is
        never touched (tenant isolation)."""

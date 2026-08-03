"""Port: emit an immutable audit/provenance record for a governance action (ADR 0012 P5).

A revocation is a governance action on the vetted corpus, so it must leave a
durable, queryable trail: WHO revoked WHICH entry, WHEN, and WHY. That is both a
security requirement (revocation is the poisoning-residual lever — every use must
be attributable) and the "AI/governance actions → provenance" principle applied to
a human governance action.

Shaped to the one verb remediation needs (``log_revocation``). The adapter delegates
to the ``audit`` context's application surface (the shared ``EntityAuditLog``) — a
permitted cross-context *application* reach — and NEVER touches the RemediationEntry
ORM model (the sole-writer invariant, D1, forbids any other file importing it). An
audit-write failure must never fail the revocation itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class RemediationAuditPort(ABC):
    @abstractmethod
    def log_revocation(
        self,
        *,
        entry_id: UUID,
        workspace_id: UUID,
        actor_id: str | None,
        reason: str,
    ) -> None:
        """Record that ``entry_id`` was revoked from the corpus by ``actor_id``.

        Best-effort: implementations MUST swallow their own write failures (logged,
        never raised) — the revocation is already committed and must not be undone
        by an audit hiccup."""

"""Port: may this actor perform a governance action on the corpus? (ADR 0012 P5)

Revocation strips a vetted fix from the retrievable corpus — security-sensitive in
both directions: an attacker who could revoke freely could hollow out a workspace's
proven fixes, and revoking a *good* fix to make room for a poisoned one is a real
attack shape. So revocation is **governance-gated**: only a workspace owner/admin
may do it (the adapter checks membership role against the workspace persistence).

Shaped to the gate's need (a boolean), not to any RBAC internals — the adapter
decides *how* "owner/admin" is determined. The use case ALSO accepts a
sign-off-approved path as an alternative authorization (via the existing
``SignOffGatePort``), so this port answers only the owner/admin question; either
gate passing authorizes the action.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class RemediationGovernancePort(ABC):
    @abstractmethod
    def can_revoke(self, *, workspace_id: UUID, actor_user_id: str | None) -> bool:
        """True iff *actor_user_id* is a workspace owner/admin of *workspace_id*.

        Fail-closed: a missing actor, a non-member, or a member without the
        owner/admin role is ``False`` — a governance gate must treat "no proof of
        authority" as "denied"."""

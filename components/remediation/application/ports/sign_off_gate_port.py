"""Port: is this remediation's sign-off APPROVED?

Shaped to the gate's need (a boolean), not to the sign_off kernel's API. The
adapter (``infrastructure/adapters/``) delegates to ``sign_off``'s *application*
surface (``require_approved`` / the registry's ``get_state``) — a permitted
cross-context call into another context's application layer, never its
infrastructure. This keeps the entry-gate's approval check honest without the
remediation context knowing how sign-off stores state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SignOffGatePort(ABC):
    @abstractmethod
    def is_approved(self, *, artifact_type: str, artifact_id: str) -> bool:
        """True iff a sign-off record for ``(artifact_type, artifact_id)`` is in
        the APPROVED state. Any non-approved or unregistered state is False —
        the gate treats "no proof of approval" as "not approved" (fail-closed)."""

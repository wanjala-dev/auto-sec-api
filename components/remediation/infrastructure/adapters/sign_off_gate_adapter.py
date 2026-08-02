"""Adapter: read sign-off approval via the sign_off *application* surface.

Implements :class:`SignOffGatePort` by delegating to ``sign_off``'s
``require_approved`` gate function — a permitted cross-context call into another
context's application layer (never its infrastructure; sign_off has no ORM of its
own anyway). Fail-closed: any non-approved state, and an unregistered artifact
type, both resolve to ``False``. The entry-gate must treat "no proof of approval"
as "not approved" — the whole point of D1 is that membership is earned, so an
ambiguous approval signal must never admit an entry.
"""

from __future__ import annotations

from components.remediation.application.ports.sign_off_gate_port import SignOffGatePort
from components.sign_off.application.services.require_approved import require_approved
from components.sign_off.domain.errors import NotApprovedError, UnregisteredArtifactError


class SignOffGateAdapter(SignOffGatePort):
    def is_approved(self, *, artifact_type: str, artifact_id: str) -> bool:
        try:
            require_approved(artifact_type, artifact_id)
        except (NotApprovedError, UnregisteredArtifactError):
            return False
        return True

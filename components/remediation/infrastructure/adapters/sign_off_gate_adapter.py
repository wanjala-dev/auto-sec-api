"""Adapter: read sign-off approval via the sign_off *application* surface.

Implements :class:`SignOffGatePort` by delegating to ``sign_off``'s
``require_approved`` gate function — a permitted cross-context call into another
context's application layer (never its infrastructure; sign_off has no ORM of its
own anyway). Fail-closed: ANY sign-off failure — a non-approved state, an
unregistered artifact type, or an unexpected lookup error a future registered
adapter might raise (``DoesNotExist`` / a DB error surfacing as ``SignOffError``)
— resolves to ``False``. The entry-gate must treat "no proof of approval" as "not
approved": the whole point of D1 is that membership is earned, so an ambiguous or
erroring approval signal must never admit an entry, and must never crash the gate.
"""

from __future__ import annotations

import logging

from components.remediation.application.ports.sign_off_gate_port import SignOffGatePort
from components.sign_off.application.services.require_approved import require_approved
from components.sign_off.domain.errors import SignOffError

logger = logging.getLogger(__name__)


class SignOffGateAdapter(SignOffGatePort):
    def is_approved(self, *, artifact_type: str, artifact_id: str) -> bool:
        try:
            require_approved(artifact_type, artifact_id)
        except SignOffError:
            # The expected domain path: NotApprovedError / UnregisteredArtifactError
            # (and any other sign-off-domain failure) all mean "not proven
            # approved" ⇒ fail closed. INFO so a refusal is greppable, not silent.
            logger.info(
                "remediation_sign_off_gate_not_approved artifact_type=%s artifact_id=%s",
                artifact_type,
                artifact_id,
            )
            return False
        except Exception:
            # Fail-closed BACKSTOP (deliberate, documented — the one case the
            # logging rule sanctions catching broadly): a future registered
            # sign-off adapter's get_state could raise something outside the
            # SignOffError taxonomy (ObjectDoesNotExist, a DB/connection error).
            # A security gate must never crash open on an unexpected error — it
            # denies. The traceback is preserved (logger.exception), so this is a
            # loud deny, not a swallow.
            logger.exception(
                "remediation_sign_off_gate_errored_failing_closed artifact_type=%s artifact_id=%s",
                artifact_type,
                artifact_id,
            )
            return False
        return True

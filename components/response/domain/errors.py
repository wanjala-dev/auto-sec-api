"""Response-context domain errors — mapped onto the shared exception taxonomy.

Each subclasses both ``ResponseActionError`` (so callers can catch the whole
context at once) and the matching shared-kernel base (so controllers/middleware
get uniform HTTP mapping): not-found → 404, illegal transition → conflict/409,
unsafe/precondition → validation/422.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class ResponseActionError(DomainError):
    """Base for response-action domain failures."""


class ResponseActionNotFoundError(ResponseActionError, NotFoundError):
    def __init__(self, action_id: str) -> None:
        super().__init__(f"response action {action_id} not found")
        self.action_id = action_id


class IllegalTransitionError(ResponseActionError, ConflictError):
    """A lifecycle decision was attempted from a state that does not allow it
    (e.g. approving an already-executed action, rolling back a proposal)."""

    def __init__(self, action_id: str, status: str, decision: str) -> None:
        super().__init__(f"cannot {decision} response action {action_id} in state {status}")
        self.action_id = action_id
        self.status = status
        self.decision = decision


class UnsafeActionError(ResponseActionError, ValidationError):
    """The proposed action fails a safety invariant (e.g. the target rule is not
    a public exposure, so revoking it is out of scope for this action)."""

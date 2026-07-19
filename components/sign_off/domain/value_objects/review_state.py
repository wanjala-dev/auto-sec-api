"""Review-state value object + the legal transition map.

The state machine is the spine every onboarded artifact shares. An artifact
enters ``PENDING`` when AI- or template-generated, and only ``APPROVED`` unlocks
the downstream send/apply action (enforced by ``require_approved``).

Editing an already-approved artifact must invalidate the approval — the adapter
transitions ``APPROVED -> PENDING`` so a human re-signs whatever changed. That
prevents the "approve clean copy, then edit in a falsehood, then send" hole.
"""

from __future__ import annotations

from enum import Enum

from components.sign_off.domain.errors import IllegalTransitionError


class ReviewState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


# Legal transitions. REJECTED is terminal. APPROVED -> PENDING is allowed so an
# edit after sign-off re-opens review (approval is never sticky across edits).
_TRANSITIONS: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.PENDING: frozenset(
        {ReviewState.APPROVED, ReviewState.CHANGES_REQUESTED, ReviewState.REJECTED}
    ),
    ReviewState.CHANGES_REQUESTED: frozenset({ReviewState.PENDING, ReviewState.REJECTED}),
    ReviewState.APPROVED: frozenset({ReviewState.PENDING}),
    ReviewState.REJECTED: frozenset(),
}


def can_transition(src: ReviewState, dst: ReviewState) -> bool:
    """True if ``src -> dst`` is a legal review-state transition."""
    return dst in _TRANSITIONS.get(src, frozenset())


def assert_transition(src: ReviewState, dst: ReviewState) -> None:
    """Raise ``IllegalTransitionError`` unless ``src -> dst`` is legal."""
    if not can_transition(src, dst):
        raise IllegalTransitionError(src, dst)

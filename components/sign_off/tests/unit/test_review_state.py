"""State-machine tests — the transitions the whole spine relies on."""

from __future__ import annotations

import pytest

from components.sign_off.domain.errors import IllegalTransitionError
from components.sign_off.domain.value_objects.review_state import (
    ReviewState,
    assert_transition,
    can_transition,
)

pytestmark = pytest.mark.unit

S = ReviewState


@pytest.mark.parametrize(
    "src,dst",
    [
        (S.PENDING, S.APPROVED),
        (S.PENDING, S.CHANGES_REQUESTED),
        (S.PENDING, S.REJECTED),
        (S.CHANGES_REQUESTED, S.PENDING),
        (S.CHANGES_REQUESTED, S.REJECTED),
        (S.APPROVED, S.PENDING),  # an edit after sign-off re-opens review
    ],
)
def test_legal_transitions(src, dst):
    assert can_transition(src, dst)
    assert_transition(src, dst)  # does not raise


@pytest.mark.parametrize(
    "src,dst",
    [
        (S.REJECTED, S.PENDING),  # rejected is terminal
        (S.REJECTED, S.APPROVED),
        (S.APPROVED, S.REJECTED),  # can't reject an approved artifact without re-opening
        (S.APPROVED, S.CHANGES_REQUESTED),
        (S.CHANGES_REQUESTED, S.APPROVED),  # must resubmit (-> pending) before approval
        (S.PENDING, S.PENDING),  # no self-loop
    ],
)
def test_illegal_transitions_raise(src, dst):
    assert not can_transition(src, dst)
    with pytest.raises(IllegalTransitionError):
        assert_transition(src, dst)


def test_approved_reopens_on_edit_then_can_be_reapproved():
    # The "approve clean, then edit a lie, then send" hole is closed because an
    # edit drops APPROVED -> PENDING, and PENDING -> APPROVED is a fresh sign-off.
    assert can_transition(S.APPROVED, S.PENDING)
    assert can_transition(S.PENDING, S.APPROVED)

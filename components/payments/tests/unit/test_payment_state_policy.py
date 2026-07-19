from __future__ import annotations

from components.payments.domain.policies.payment_state_policy import (
    can_transition_attempt,
    can_transition_dispute,
    can_transition_order,
    can_transition_payout,
    can_transition_refund,
)


class TestOrderTransitions:
    def test_pending_to_processing(self):
        assert can_transition_order("pending", "processing")

    def test_pending_to_succeeded_blocked(self):
        assert not can_transition_order("pending", "succeeded")

    def test_succeeded_is_terminal(self):
        assert not can_transition_order("succeeded", "pending")
        assert not can_transition_order("succeeded", "failed")


class TestRefundTransitions:
    def test_pending_to_processing(self):
        assert can_transition_refund("pending", "processing")

    def test_pending_to_succeeded(self):
        assert can_transition_refund("pending", "succeeded")

    def test_succeeded_is_terminal(self):
        assert not can_transition_refund("succeeded", "failed")

    def test_processing_to_succeeded(self):
        assert can_transition_refund("processing", "succeeded")


class TestDisputeTransitions:
    def test_needs_response_to_under_review(self):
        assert can_transition_dispute("needs_response", "under_review")

    def test_needs_response_to_won(self):
        assert can_transition_dispute("needs_response", "won")

    def test_won_is_terminal(self):
        assert not can_transition_dispute("won", "lost")

    def test_lost_is_terminal(self):
        assert not can_transition_dispute("lost", "won")


class TestPayoutTransitions:
    def test_pending_to_in_transit(self):
        assert can_transition_payout("pending", "in_transit")

    def test_in_transit_to_paid(self):
        assert can_transition_payout("in_transit", "paid")

    def test_paid_is_terminal(self):
        assert not can_transition_payout("paid", "failed")

    def test_unknown_state_returns_false(self):
        assert not can_transition_payout("unknown", "paid")


class TestAttemptTransitions:
    def test_created_to_processing(self):
        assert can_transition_attempt("created", "processing")

    def test_succeeded_is_terminal(self):
        assert not can_transition_attempt("succeeded", "failed")

"""Codifies valid state transitions for all payment-related entities.

Pure functions with no side effects — safe to call from any layer.
"""

from __future__ import annotations

_ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"processing", "failed", "canceled"}),
    "processing": frozenset({"succeeded", "failed", "requires_action"}),
    "requires_action": frozenset({"processing", "succeeded", "failed", "canceled"}),
    "succeeded": frozenset(),
    "failed": frozenset({"pending"}),
    "canceled": frozenset(),
}

_ATTEMPT_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"processing", "succeeded", "failed", "canceled", "requires_action"}),
    "processing": frozenset({"succeeded", "failed", "requires_action"}),
    "requires_action": frozenset({"processing", "succeeded", "failed", "canceled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}

_REFUND_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"processing", "succeeded", "failed", "canceled"}),
    "processing": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}

_DISPUTE_TRANSITIONS: dict[str, frozenset[str]] = {
    "warning_needs_response": frozenset({"warning_under_review", "needs_response", "won", "lost", "accepted"}),
    "warning_under_review": frozenset({"won", "lost", "accepted"}),
    "needs_response": frozenset({"under_review", "won", "lost", "accepted"}),
    "under_review": frozenset({"won", "lost", "accepted"}),
    "won": frozenset(),
    "lost": frozenset(),
    "accepted": frozenset(),
}

_PAYOUT_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"in_transit", "paid", "failed", "canceled"}),
    "in_transit": frozenset({"paid", "failed", "canceled"}),
    "paid": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}


def can_transition_order(current: str, target: str) -> bool:
    return target in _ORDER_TRANSITIONS.get(current, frozenset())


def can_transition_attempt(current: str, target: str) -> bool:
    return target in _ATTEMPT_TRANSITIONS.get(current, frozenset())


def can_transition_refund(current: str, target: str) -> bool:
    return target in _REFUND_TRANSITIONS.get(current, frozenset())


def can_transition_dispute(current: str, target: str) -> bool:
    return target in _DISPUTE_TRANSITIONS.get(current, frozenset())


def can_transition_payout(current: str, target: str) -> bool:
    return target in _PAYOUT_TRANSITIONS.get(current, frozenset())

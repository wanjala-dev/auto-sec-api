from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class FeeRecordingContext:
    """Everything the revenue-share fee handler needs to record a PaymentFee.

    Resolved from a ``PaymentEvent`` (which the ``PaymentSucceeded`` event
    points at). ``payment_transaction_id`` is the ``PaymentTransaction`` row
    the fee attaches to (``PaymentFee.transaction`` FK) — NOT the budgeting
    Transaction.
    """

    payment_transaction_id: UUID
    method_id: UUID
    workspace_id: UUID | None
    provider: str
    currency: str
    monetization_mode: str
    revenue_share_bps: int
    # Connect identifiers for the one-time fee lookup (charge not on the
    # session payload). Empty when not resolvable.
    payment_intent_id: str
    stripe_account_id: str
    # True when a PaymentFee already exists for this PaymentTransaction —
    # the handler skips to stay idempotent across replays / multiple
    # success events (checkout + charge + invoice all publish PaymentSucceeded).
    fee_already_recorded: bool


class FeeRecordingContextPort(Protocol):
    def resolve(self, *, payment_event_id: UUID) -> FeeRecordingContext | None:
        """Resolve the fee-recording context for a payment event.

        Returns ``None`` when no succeeded ``PaymentTransaction`` can be tied
        to the event yet (e.g. the capture row was not recorded) — the handler
        then records nothing rather than guessing.
        """
        ...

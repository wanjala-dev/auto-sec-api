from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class PaymentEventReceived(DomainEvent):
    payment_event_id: UUID
    provider: str
    provider_event_id: str
    event_type: str


@dataclass(frozen=True, kw_only=True)
class PaymentEventClaimed(DomainEvent):
    payment_event_id: UUID
    provider: str
    claimed_by: str


@dataclass(frozen=True, kw_only=True)
class PaymentCaptured(DomainEvent):
    order_id: UUID
    attempt_id: UUID
    provider: str


@dataclass(frozen=True, kw_only=True)
class PaymentFailed(DomainEvent):
    order_id: UUID | None
    attempt_id: UUID | None
    provider: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class PaymentRefunded(DomainEvent):
    refund_id: UUID
    transaction_id: UUID
    provider: str
    amount: str
    currency: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class PaymentDisputed(DomainEvent):
    dispute_id: UUID
    transaction_id: UUID
    provider: str
    category: str
    amount: str
    currency: str


@dataclass(frozen=True, kw_only=True)
class PaymentPayoutCompleted(DomainEvent):
    payout_id: UUID
    workspace_id: UUID
    provider: str
    amount: str
    currency: str


@dataclass(frozen=True, kw_only=True)
class PaymentFeeRecorded(DomainEvent):
    fee_id: UUID
    transaction_id: UUID
    provider: str
    fee_amount: str
    context: str


@dataclass(frozen=True, kw_only=True)
class PaymentSucceeded(DomainEvent):
    """Published when any payment event is successfully processed.

    Carries all data downstream handlers need so they never have to
    query the database.  Every source type (donation, sponsorship,
    campaign, event, shop) that flows through
    ``mark_payment_event_processed()`` publishes this event.
    """
    payment_event_id: UUID
    workspace_id: str = ""
    provider: str = ""
    event_type: str = ""
    context: str = ""
    amount: str = "0"
    currency: str = "USD"
    # The Connect ``application_fee_amount`` Stripe actually took on this charge,
    # in MINOR units (cents), as a string. Present on ``charge.succeeded`` and
    # ``invoice.payment_succeeded`` payloads; absent ("0") on the one-time
    # ``checkout.session.completed`` payload (the fee lives on the charge, which
    # the session payload does not expand). The revenue-share fee handler reads
    # this when present and otherwise fetches the real fee from Stripe. Empty /
    # "0" means "not on this payload" — never "the fee was zero".
    application_fee_amount: str = "0"
    payer_name: str = ""
    payer_email: str = ""
    recipient_id: str = ""
    recipient_name: str = ""
    project_id: str = ""
    campaign_id: str = ""
    event_id: str = ""
    metadata: dict = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from components.payments.application.use_cases.record_and_claim_payment_event_use_case import (
    RecordAndClaimPaymentEventUseCase,
)
from components.payments.domain.entities.payment_event_entity import PaymentEventEntity
from components.payments.application.ports.payment_event_recording_port import (
    RecordedPaymentEvent,
)


@dataclass
class FakePaymentEventRecorder:
    recorded: RecordedPaymentEvent

    def record_if_new(
        self,
        *,
        provider: str,
        provider_account_id: str | None,
        provider_event_id: str,
        external_id: str | None,
        event_type: str,
        workspace_id,
        method_id,
        amount: Decimal | None,
        currency: str | None,
        payload,
    ) -> RecordedPaymentEvent:
        return self.recorded


@dataclass
class FakePaymentEventClaims:
    claimed: bool = False
    last_claim_message: str | None = None

    def claim_event(self, *, payment_event_id, claimed_by: str, message: str | None = None) -> bool:
        self.last_claim_message = message
        return self.claimed


def test_record_and_claim_payment_event_use_case_returns_existing_payment_event_metadata():
    event_id = uuid4()
    recorder = FakePaymentEventRecorder(
        recorded=RecordedPaymentEvent(
            record=PaymentEventEntity(
                id=event_id,
                provider="stripe",
                provider_event_id="evt_123",
                event_type="checkout.session.completed",
                status="received",
            ),
            is_new=True,
        ),
    )
    claims = FakePaymentEventClaims(claimed=True)
    use_case = RecordAndClaimPaymentEventUseCase(recorder, claims)

    result = use_case.execute(
        provider="stripe",
        provider_account_id="acct_123",
        provider_event_id="evt_123",
        external_id="pi_123",
        event_type="checkout.session.completed",
        workspace_id=None,
        method_id=None,
        amount=Decimal("10.00"),
        currency="usd",
        payload={"id": "evt_123"},
        claimed_by="test-suite",
        message="Webhook received.",
    )

    assert result.payment_event_id == event_id
    assert result.is_new is True
    assert result.claimed is True
    assert claims.last_claim_message == "Webhook received."

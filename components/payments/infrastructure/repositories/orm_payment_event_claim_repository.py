from __future__ import annotations

from uuid import UUID

from components.payments.infrastructure.adapters.payment_event_state import (
    claim_payment_event_processing,
)
from components.payments.application.ports.payment_event_claim_port import PaymentEventClaimPort
from infrastructure.persistence.workspaces.payments.models import PaymentEvent


class OrmPaymentEventClaimRepository(PaymentEventClaimPort):
    """Transitional adapter for payment-event claim/worker-state transitions."""

    def claim_event(
        self,
        *,
        payment_event_id: UUID,
        claimed_by: str,
        message: str | None = None,
    ) -> bool:
        event = PaymentEvent.objects.filter(id=payment_event_id).first()
        if not event:
            return False

        claim_message = message or f"Claimed by {claimed_by}."
        return claim_payment_event_processing(event, claim_message)

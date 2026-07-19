from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.application.ports.payment_event_claim_port import PaymentEventClaimPort
from components.payments.application.ports.payment_event_recording_port import (
    PaymentEventRecordingPort,
)


@dataclass(frozen=True)
class RecordAndClaimPaymentEventResult:
    payment_event_id: UUID | None
    is_new: bool
    claimed: bool


class RecordAndClaimPaymentEventUseCase:
    """Application use case for idempotent inbound payment-event intake and claim."""

    def __init__(
        self,
        payment_event_recorder: PaymentEventRecordingPort,
        payment_event_claims: PaymentEventClaimPort,
    ):
        self.payment_event_recorder = payment_event_recorder
        self.payment_event_claims = payment_event_claims

    def execute(
        self,
        *,
        provider: str,
        provider_account_id: str | None,
        provider_event_id: str,
        external_id: str | None,
        event_type: str,
        workspace_id: UUID | None,
        method_id: UUID | None,
        amount: Decimal | None,
        currency: str | None,
        payload: dict[str, Any] | None,
        claimed_by: str,
        message: str | None = None,
    ) -> RecordAndClaimPaymentEventResult:
        recorded = self.payment_event_recorder.record_if_new(
            provider=provider,
            provider_account_id=provider_account_id,
            provider_event_id=provider_event_id,
            external_id=external_id,
            event_type=event_type,
            workspace_id=workspace_id,
            method_id=method_id,
            amount=amount,
            currency=currency,
            payload=payload,
        )
        if not recorded.record:
            return RecordAndClaimPaymentEventResult(
                payment_event_id=None,
                is_new=False,
                claimed=False,
            )

        claimed = self.payment_event_claims.claim_event(
            payment_event_id=recorded.record.id,
            claimed_by=claimed_by,
            message=message,
        )
        return RecordAndClaimPaymentEventResult(
            payment_event_id=recorded.record.id,
            is_new=recorded.is_new,
            claimed=claimed,
        )

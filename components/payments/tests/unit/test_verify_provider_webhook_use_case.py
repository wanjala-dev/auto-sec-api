from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from components.payments.application.use_cases.record_and_claim_payment_event_use_case import (
    RecordAndClaimPaymentEventResult,
)
from components.payments.application.use_cases.verify_provider_webhook_use_case import (
    VerifiedProviderWebhookEnvelope,
    VerifyProviderWebhookUseCase,
)


@dataclass
class FakeIntakeService:
    last_kwargs: dict | None = None

    def execute(self, **kwargs) -> RecordAndClaimPaymentEventResult:
        self.last_kwargs = kwargs
        return RecordAndClaimPaymentEventResult(
            payment_event_id=uuid4(),
            is_new=True,
            claimed=True,
        )


def test_verify_provider_webhook_use_case_extracts_stripe_fields_from_dict_payload():
    intake_service = FakeIntakeService()
    envelope = VerifiedProviderWebhookEnvelope(
        provider="stripe",
        account_id="acct_123",
        workspace_id=None,
        method_id=None,
        event={
            "id": "evt_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_123",
                    "amount_total": 5000,
                    "currency": "usd",
                }
            },
        },
    )

    result = VerifyProviderWebhookUseCase(intake_service).execute(
        envelope=envelope,
        claimed_by="test-suite",
        claim_message="Webhook received.",
    )

    assert result.intake.is_new is True
    assert intake_service.last_kwargs is not None
    assert intake_service.last_kwargs["provider_event_id"] == "evt_123"
    assert intake_service.last_kwargs["external_id"] == "cs_123"
    assert intake_service.last_kwargs["event_type"] == "checkout.session.completed"
    assert intake_service.last_kwargs["currency"] == "usd"
    assert result.normalized_event["id"] == "evt_123"

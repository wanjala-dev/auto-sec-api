from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from components.payments.application.use_cases.attach_provider_attempt_reference_use_case import (
    AttachProviderAttemptReferenceUseCase,
)


@dataclass
class FakePaymentOrderStore:
    processing: list[dict] = None

    def __post_init__(self):
        self.processing = []

    def mark_checkout_processing(self, **kwargs) -> None:
        self.processing.append(kwargs)


def test_attach_provider_attempt_reference_use_case_attaches_stripe_session_reference():
    repository = FakePaymentOrderStore()
    order_id = uuid4()
    attempt_id = uuid4()

    AttachProviderAttemptReferenceUseCase(repository).execute(
        order_id=order_id,
        attempt_id=attempt_id,
        checkout_payload={"provider": "stripe", "sessionId": "cs_123"},
    )

    assert repository.processing == [
        {
            "order_id": order_id,
            "attempt_id": attempt_id,
            "gateway_reference": "cs_123",
            "gateway_reference_type": "checkout_session",
        }
    ]


def test_attach_provider_attempt_reference_use_case_falls_back_to_empty_reference():
    repository = FakePaymentOrderStore()
    order_id = uuid4()
    attempt_id = uuid4()

    AttachProviderAttemptReferenceUseCase(repository).execute(
        order_id=order_id,
        attempt_id=attempt_id,
        checkout_payload={"provider": "other"},
    )

    assert repository.processing == [
        {
            "order_id": order_id,
            "attempt_id": attempt_id,
            "gateway_reference": "",
            "gateway_reference_type": "",
        }
    ]

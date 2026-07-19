from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from components.payments.application.use_cases.mark_checkout_failed_use_case import (
    MarkCheckoutFailedUseCase,
)


@dataclass
class FakePaymentOrderStore:
    failed: list[dict] = None

    def __post_init__(self):
        self.failed = []

    def mark_checkout_failed(self, **kwargs) -> None:
        self.failed.append(kwargs)


def test_mark_checkout_failed_use_case_delegates_to_order_store():
    repository = FakePaymentOrderStore()
    order_id = uuid4()
    attempt_id = uuid4()

    MarkCheckoutFailedUseCase(repository).execute(
        order_id=order_id,
        attempt_id=attempt_id,
        message="gateway failed",
    )

    assert repository.failed == [
        {
            "order_id": order_id,
            "attempt_id": attempt_id,
            "message": "gateway failed",
        }
    ]

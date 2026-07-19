from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from components.payments.application.use_cases.create_payment_order_use_case import (
    CreatePaymentOrderUseCase,
)
from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity


@dataclass
class FakePaymentOrderStore:
    order_record: PaymentOrderEntity
    calls: list[dict] = None

    def __post_init__(self):
        self.calls = []

    def create_order(self, **kwargs) -> PaymentOrderEntity:
        self.calls.append(kwargs)
        return self.order_record


def test_create_payment_order_use_case_delegates_to_order_store():
    method_id = uuid4()
    order_record = PaymentOrderEntity(
        id=uuid4(),
        method_id=method_id,
        context="workspace_support",
        status="pending",
        amount=Decimal("10.00"),
        currency="usd",
        attempt_id=uuid4(),
        attempt_status="created",
        attempt_idempotency_key="attempt-key",
        metadata={"ctx": "workspace_support"},
    )
    repository = FakePaymentOrderStore(order_record=order_record)

    result = CreatePaymentOrderUseCase(repository).execute(
        method_id=method_id,
        context="workspace_support",
        amount=Decimal("10.00"),
        currency="usd",
        customer_email="donor@example.com",
        customer_name="Donor",
        plan_id=None,
        client_reference_id="ref_123",
        metadata={"ctx": "workspace_support"},
    )

    assert result == order_record
    assert repository.calls == [
        {
            "method_id": method_id,
            "context": "workspace_support",
            "amount": Decimal("10.00"),
            "currency": "usd",
            "customer_email": "donor@example.com",
            "customer_name": "Donor",
            "plan_id": None,
            "client_reference_id": "ref_123",
            "metadata": {"ctx": "workspace_support"},
        }
    ]

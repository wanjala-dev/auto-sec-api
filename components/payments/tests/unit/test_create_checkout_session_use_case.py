from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from components.payments.application.use_cases.attach_provider_attempt_reference_use_case import (
    AttachProviderAttemptReferenceUseCase,
)
from components.payments.application.use_cases.create_checkout_session_use_case import (
    CreateCheckoutSessionUseCase,
)
from components.payments.application.use_cases.create_payment_order_use_case import (
    CreatePaymentOrderUseCase,
)
from components.payments.application.use_cases.mark_checkout_failed_use_case import (
    MarkCheckoutFailedUseCase,
)
from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity


@dataclass
class FakePaymentOrderStorePort:
    order_record: PaymentOrderEntity
    failed: list[tuple] = None
    processing: list[tuple] = None

    def __post_init__(self):
        self.failed = []
        self.processing = []

    def create_order(self, **kwargs) -> PaymentOrderEntity:
        return self.order_record

    def mark_checkout_failed(self, *, order_id, attempt_id, message: str) -> None:
        self.failed.append((order_id, attempt_id, message))

    def mark_checkout_processing(
        self,
        *,
        order_id,
        attempt_id,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None:
        self.processing.append((order_id, attempt_id, gateway_reference, gateway_reference_type))


class FakeGateway:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create_checkout_session(self, method, plan, **kwargs):
        self.calls.append((method, plan, kwargs))
        return self.payload


class FailingGateway:
    def __init__(self, error: Exception):
        self.error = error
        self.calls = []

    def create_checkout_session(self, method, plan, **kwargs):
        self.calls.append((method, plan, kwargs))
        raise self.error


def test_create_checkout_session_use_case_marks_processing_for_stripe_session():
    order_id = uuid4()
    attempt_id = uuid4()
    repository = FakePaymentOrderStorePort(
        order_record=PaymentOrderEntity(
            id=order_id,
            method_id=uuid4(),
            context="workspace_support",
            status="pending",
            amount=Decimal("10.00"),
            currency="usd",
            attempt_id=attempt_id,
            attempt_status="created",
            attempt_idempotency_key="attempt-key",
            metadata={"ctx": "workspace_support"},
        )
    )
    gateway = FakeGateway({"provider": "stripe", "sessionId": "cs_123"})
    use_case = CreateCheckoutSessionUseCase(
        create_payment_order=CreatePaymentOrderUseCase(repository),
        mark_checkout_failed=MarkCheckoutFailedUseCase(repository),
        attach_provider_attempt_reference=AttachProviderAttemptReferenceUseCase(
            repository
        ),
    )
    method = SimpleNamespace(id=repository.order_record.method_id)

    result = use_case.execute(
        gateway=gateway,
        method=method,
        plan=None,
        context="workspace_support",
        amount=Decimal("10.00"),
        currency="usd",
        success_url="https://example.org/success",
        cancel_url="https://example.org/cancel",
        customer_email="donor@example.com",
        customer_id=None,
        client_reference_id=None,
        metadata={"ctx": "workspace_support"},
        customer_name="Donor",
    )

    assert result.order_id == order_id
    assert result.attempt_id == attempt_id
    assert repository.failed == []
    assert repository.processing == [
        (order_id, attempt_id, "cs_123", "checkout_session")
    ]


def test_create_checkout_session_use_case_marks_checkout_failed_on_gateway_error():
    order_id = uuid4()
    attempt_id = uuid4()
    repository = FakePaymentOrderStorePort(
        order_record=PaymentOrderEntity(
            id=order_id,
            method_id=uuid4(),
            context="workspace_support",
            status="pending",
            amount=Decimal("10.00"),
            currency="usd",
            attempt_id=attempt_id,
            attempt_status="created",
            attempt_idempotency_key="attempt-key",
            metadata={"ctx": "workspace_support"},
        )
    )
    gateway = FailingGateway(RuntimeError("gateway failed"))
    use_case = CreateCheckoutSessionUseCase(
        create_payment_order=CreatePaymentOrderUseCase(repository),
        mark_checkout_failed=MarkCheckoutFailedUseCase(repository),
        attach_provider_attempt_reference=AttachProviderAttemptReferenceUseCase(
            repository
        ),
    )
    method = SimpleNamespace(id=repository.order_record.method_id)

    try:
        use_case.execute(
            gateway=gateway,
            method=method,
            plan=None,
            context="workspace_support",
            amount=Decimal("10.00"),
            currency="usd",
            success_url="https://example.org/success",
            cancel_url="https://example.org/cancel",
            customer_email="donor@example.com",
            customer_id=None,
            client_reference_id=None,
            metadata={"ctx": "workspace_support"},
            customer_name="Donor",
        )
    except RuntimeError as exc:
        assert str(exc) == "gateway failed"
    else:
        raise AssertionError("expected gateway failure")

    assert repository.failed == [
        (order_id, attempt_id, "gateway failed")
    ]
    assert repository.processing == []

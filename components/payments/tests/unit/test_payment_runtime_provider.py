from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from components.payments.application.providers.payment_runtime_provider import (
    PaymentRuntimeProvider,
)
from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity


class FakeGatewayProvider:
    def __init__(self, gateway):
        self.gateway = gateway
        self.requested = []

    def get_gateway_for_provider(self, provider_slug: str):
        self.requested.append(provider_slug)
        return self.gateway


class FakeGateway:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create_checkout_session(self, method, plan, **kwargs):
        self.calls.append((method, plan, kwargs))
        return self.payload


@dataclass
class FakePaymentOrderStore:
    order_record: PaymentOrderEntity
    processing: list[tuple] = None

    def __post_init__(self):
        self.processing = []

    def create_order(self, **kwargs):
        metadata = dict(kwargs.get("metadata") or {})
        return replace(self.order_record, metadata=metadata)

    def mark_checkout_failed(self, *, order_id, attempt_id, message: str) -> None:
        raise AssertionError(f"unexpected checkout failure: {message}")

    def mark_checkout_processing(
        self,
        *,
        order_id,
        attempt_id,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None:
        self.processing.append((order_id, attempt_id, gateway_reference, gateway_reference_type))


class FakePaymentMethodSelection:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve_method(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakePaymentPlanStore:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve_plan_for_method(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeWebhookVerifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify(self, request, endpoint_name=None):
        self.calls.append((request, endpoint_name))
        return self.result


def test_payment_runtime_provider_resolves_method_and_plan():
    selection = FakePaymentMethodSelection("method")
    plan_store = FakePaymentPlanStore("plan")
    provider = PaymentRuntimeProvider(
        payment_method_selection=selection,
        payment_plans=plan_store,
    )

    resolved = provider.resolve_method_and_plan(
        workspace="workspace",
        context="recipient_sponsorship",
        payment_method_id="method-id",
        plan_slug="monthly",
        recipient="recipient",
        prefer_recurring=True,
    )

    assert resolved == ("method", "plan")
    assert selection.calls[0]["context"] == "recipient_sponsorship"
    assert plan_store.calls[0]["plan_slug"] == "monthly"
    assert plan_store.calls[0]["method"] == "method"


def test_payment_runtime_provider_creates_checkout_and_adds_order_metadata():
    order_id = uuid4()
    attempt_id = uuid4()
    repository = FakePaymentOrderStore(
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
            metadata={},
        )
    )
    gateway = FakeGateway({"provider": "stripe", "sessionId": "cs_123"})
    provider = PaymentRuntimeProvider(
        gateway_provider=FakeGatewayProvider(gateway),
        payment_orders=repository,
    )
    method = SimpleNamespace(
        id=repository.order_record.method_id,
        provider=SimpleNamespace(slug="stripe-connect"),
    )

    checkout = provider.create_checkout_session(
        method,
        None,
        amount=Decimal("10.00"),
        currency="usd",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
        customer_email="donor@example.com",
        client_reference_id="ref_123",
        metadata={"name": "Donor"},
        context="workspace_support",
    )

    assert checkout["orderId"] == str(order_id)
    assert checkout["attemptId"] == str(attempt_id)
    assert gateway.calls[0][2]["metadata"]["ctx"] == "workspace_support"
    assert repository.processing == [(order_id, attempt_id, "cs_123", "checkout_session")]


def test_payment_runtime_provider_maps_webhook_verification_result():
    verifier = FakeWebhookVerifier(
        SimpleNamespace(
            event={"id": "evt_123"},
            method="method",
            workspace="workspace",
            account_id="acct_123",
            legacy_context="legacy",
            provider_slug="stripe",
            payment_event="payment_event",
            payment_event_duplicate=True,
            payment_event_processable=False,
            api_key="sk_test",
        )
    )
    provider = PaymentRuntimeProvider(webhook_verifier=verifier)
    request = object()

    result = provider.verify_webhook(request, "donations")

    assert result.provider_slug == "stripe"
    assert result.payment_event_duplicate is True
    assert result.api_key == "sk_test"
    assert verifier.calls == [(request, "donations")]

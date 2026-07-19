from __future__ import annotations

from decimal import Decimal

from components.payments.application.use_cases.record_successful_payment_use_case import (
    RecordSuccessfulPaymentUseCase,
)


class _FakePaymentTransactions:
    def __init__(self):
        self.calls = []

    def record_transaction(self, **kwargs):
        self.calls.append(kwargs)
        return None


class _FakeFinalizeSuccessfulPaymentUseCase:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return None


def test_record_successful_payment_use_case_records_transaction_then_finalizes_state():
    payment_transactions = _FakePaymentTransactions()
    finalize_successful_payment = _FakeFinalizeSuccessfulPaymentUseCase()

    RecordSuccessfulPaymentUseCase(
        payment_transactions=payment_transactions,
        finalize_successful_payment=finalize_successful_payment,
    ).execute(
        order="order-1",
        attempt="attempt-1",
        provider="stripe",
        payment_event="evt-1",
        event_type="invoice.payment_succeeded",
        external_id="in_123",
        provider_status="paid",
        amount=Decimal("10.00"),
        currency="USD",
        payload={"id": "in_123"},
    )

    assert payment_transactions.calls == [
        {
            "order": "order-1",
            "attempt": "attempt-1",
            "provider": "stripe",
            "status": "succeeded",
            "payment_event": "evt-1",
            "event_type": "invoice.payment_succeeded",
            "external_id": "in_123",
            "provider_status": "paid",
            "amount": Decimal("10.00"),
            "currency": "USD",
            "payload": {"id": "in_123"},
            "update_statuses": False,
        }
    ]
    assert finalize_successful_payment.calls == [
        {"order": "order-1", "attempt": "attempt-1"}
    ]

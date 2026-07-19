from __future__ import annotations

from decimal import Decimal

from components.payments.application.service import (
    PaymentCaptureRecordingService,
)
from components.payments.application.ports.payment_capture_recording_port import (
    PaymentAttemptResolution,
)


class _FakeRecordingStore:
    def __init__(self):
        self.calls = []

    def resolve_order_attempt(self, *, metadata, method=None):
        self.calls.append(("resolve", metadata, method))
        return PaymentAttemptResolution(order="order-1", attempt="attempt-1")

    def sync_gateway_reference(self, *, attempt, gateway_reference, gateway_reference_type):
        self.calls.append(("sync", attempt, gateway_reference, gateway_reference_type))

    def mark_processed(self, *, payment_event, status, message):
        self.calls.append(("processed", payment_event, status, message))


class _FakePaymentTransactionStore:
    def __init__(self):
        self.calls = []

    def record_transaction(self, **kwargs):
        self.calls.append(("record", kwargs))
        return None


class _FakeRecordSuccessfulPaymentUseCase:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return None


def test_payment_capture_recording_service_records_capture_and_processed_message():
    store = _FakeRecordingStore()
    transactions = _FakePaymentTransactionStore()
    record_successful_payment_use_case = _FakeRecordSuccessfulPaymentUseCase()
    service = PaymentCaptureRecordingService(
        recording_store=store,
        payment_transactions=transactions,
        record_successful_payment_use_case=record_successful_payment_use_case,
    )

    result = service.record_capture(
        metadata={"order_id": "123"},
        method="method-1",
        gateway_reference="txn-1",
        gateway_reference_type="transaction",
        provider="braintree",
        status="succeeded",
        payment_event="evt-1",
        event_type="transaction.sale",
        external_id="txn-1",
        provider_status="settled",
        amount=Decimal("10.00"),
        currency="USD",
        payload={"id": "evt"},
        processed_status="processed",
        processed_message="Captured.",
    )

    assert result.order == "order-1"
    assert result.attempt == "attempt-1"
    assert store.calls[0] == ("resolve", {"order_id": "123"}, "method-1")
    assert store.calls[1] == ("sync", "attempt-1", "txn-1", "transaction")
    assert transactions.calls == []
    assert record_successful_payment_use_case.calls == [
        {
            "order": "order-1",
            "attempt": "attempt-1",
            "provider": "braintree",
            "payment_event": "evt-1",
            "event_type": "transaction.sale",
            "external_id": "txn-1",
            "provider_status": "settled",
            "amount": Decimal("10.00"),
            "currency": "USD",
            "payload": {"id": "evt"},
        }
    ]
    assert store.calls[2] == ("processed", "evt-1", "processed", "Captured.")


def test_payment_capture_recording_service_keeps_non_success_statuses_on_transaction_store():
    store = _FakeRecordingStore()
    transactions = _FakePaymentTransactionStore()
    record_successful_payment_use_case = _FakeRecordSuccessfulPaymentUseCase()
    service = PaymentCaptureRecordingService(
        recording_store=store,
        payment_transactions=transactions,
        record_successful_payment_use_case=record_successful_payment_use_case,
    )

    service.record_capture(
        metadata={"order_id": "123"},
        method="method-1",
        gateway_reference="txn-1",
        gateway_reference_type="transaction",
        provider="braintree",
        status="pending",
        payment_event=None,
        event_type="transaction.sale",
        external_id="txn-1",
        provider_status="submitted_for_settlement",
        amount=Decimal("10.00"),
        currency="USD",
        payload={"id": "evt"},
        update_statuses=True,
    )

    assert transactions.calls[0][1]["update_statuses"] is True
    assert record_successful_payment_use_case.calls == []

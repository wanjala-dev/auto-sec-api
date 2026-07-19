from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.application.use_cases.issue_refund_use_case import (
    IssueRefundCommand,
    IssueRefundUseCase,
)
from components.payments.domain.entities.payment_refund_entity import PaymentRefundEntity
from components.payments.domain.errors import RefundValidationError


class _FakeRefundStore:
    def __init__(self):
        self.created = []
        self.updates = []

    def create_refund(self, **kwargs):
        refund = PaymentRefundEntity(id=uuid4(), status="pending", **kwargs)
        self.created.append(refund)
        return refund

    def update_refund_status(self, **kwargs):
        self.updates.append(kwargs)
        return PaymentRefundEntity(
            id=kwargs["refund_id"],
            transaction_id=uuid4(),
            attempt_id=uuid4(),
            provider="stripe",
            status=kwargs["status"],
            reason="other",
            amount=Decimal("10.00"),
            currency="usd",
            external_id=kwargs.get("external_id", ""),
        )

    def find_by_external_id(self, **kwargs):
        return None


class _FakeBalanceTransactions:
    def __init__(self):
        self.entries = []

    def append(self, **kwargs):
        from components.payments.domain.entities.payment_balance_transaction_entity import (
            PaymentBalanceTransactionEntity,
        )

        entity = PaymentBalanceTransactionEntity(id=uuid4(), **kwargs)
        self.entries.append(entity)
        return entity


class _FakeGateway:
    def __init__(self, *, fail=False):
        self.calls = []
        self._fail = fail

    def issue_refund(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail:
            raise ConnectionError("provider down")
        return {"id": "re_provider_123", "status": "pending"}


class TestIssueRefundUseCase:
    def test_creates_refund_without_gateway(self):
        store = _FakeRefundStore()
        bal = _FakeBalanceTransactions()
        uc = IssueRefundUseCase(refund_store=store, balance_transactions=bal)

        result = uc.execute(
            IssueRefundCommand(
                transaction_id=uuid4(),
                attempt_id=uuid4(),
                provider="stripe",
                amount=Decimal("25.00"),
                currency="usd",
                reason="duplicate",
                workspace_id=uuid4(),
            )
        )

        assert result.status == "pending"
        assert len(store.created) == 1
        assert len(bal.entries) == 1
        assert bal.entries[0].transaction_type == "refund"
        assert bal.entries[0].amount == Decimal("-25.00")

    def test_calls_gateway_with_idempotency_key(self):
        store = _FakeRefundStore()
        bal = _FakeBalanceTransactions()
        gateway = _FakeGateway()
        uc = IssueRefundUseCase(refund_store=store, balance_transactions=bal, gateway=gateway)

        uc.execute(
            IssueRefundCommand(
                transaction_id=uuid4(),
                attempt_id=uuid4(),
                provider="stripe",
                amount=Decimal("10.00"),
                currency="usd",
                external_charge_id="pi_123",
                workspace_id=uuid4(),
            )
        )

        assert len(gateway.calls) == 1
        assert gateway.calls[0]["idempotency_key"]
        assert gateway.calls[0]["external_charge_id"] == "pi_123"
        # Should update status to processing after gateway success
        assert len(store.updates) == 1
        assert store.updates[0]["status"] == "processing"

    def test_marks_failed_on_gateway_error(self):
        store = _FakeRefundStore()
        bal = _FakeBalanceTransactions()
        gateway = _FakeGateway(fail=True)
        uc = IssueRefundUseCase(refund_store=store, balance_transactions=bal, gateway=gateway)

        with pytest.raises(ConnectionError):
            uc.execute(
                IssueRefundCommand(
                    transaction_id=uuid4(),
                    attempt_id=uuid4(),
                    provider="stripe",
                    amount=Decimal("10.00"),
                    currency="usd",
                    external_charge_id="pi_fail",
                )
            )

        assert len(store.updates) == 1
        assert store.updates[0]["status"] == "failed"

    def test_zero_amount_rejected(self):
        store = _FakeRefundStore()
        bal = _FakeBalanceTransactions()
        uc = IssueRefundUseCase(refund_store=store, balance_transactions=bal)

        with pytest.raises(RefundValidationError):
            uc.execute(
                IssueRefundCommand(
                    transaction_id=uuid4(),
                    attempt_id=uuid4(),
                    provider="stripe",
                    amount=Decimal("0"),
                    currency="usd",
                )
            )

    def test_no_balance_entry_without_workspace(self):
        store = _FakeRefundStore()
        bal = _FakeBalanceTransactions()
        uc = IssueRefundUseCase(refund_store=store, balance_transactions=bal)

        uc.execute(
            IssueRefundCommand(
                transaction_id=uuid4(),
                attempt_id=uuid4(),
                provider="stripe",
                amount=Decimal("10.00"),
                currency="usd",
            )
        )

        assert len(store.created) == 1
        assert len(bal.entries) == 0

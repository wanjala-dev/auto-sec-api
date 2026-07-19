from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from components.payments.application.use_cases.record_payment_fee_use_case import (
    RecordPaymentFeeCommand,
    RecordPaymentFeeUseCase,
)
from components.payments.domain.entities.payment_fee_entity import PaymentFeeEntity


class _FakeFeeStore:
    def __init__(self, *, created=True):
        self.recorded = []
        self._created = created

    def record_fee(self, **kwargs):
        fee = PaymentFeeEntity(id=uuid4(), **kwargs)
        self.recorded.append(fee)
        return fee, self._created


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


class TestRecordPaymentFeeUseCase:
    def test_records_fee_and_balance_entry(self):
        store = _FakeFeeStore()
        bal = _FakeBalanceTransactions()
        uc = RecordPaymentFeeUseCase(fee_store=store, balance_transactions=bal)

        result = uc.execute(
            RecordPaymentFeeCommand(
                transaction_id=uuid4(),
                method_id=uuid4(),
                provider="stripe",
                context="donations",
                fee_amount=Decimal("2.90"),
                currency="usd",
                fee_percentage=Decimal("2.9000"),
                fixed_fee=Decimal("0.30"),
                workspace_id=uuid4(),
            )
        )

        assert result.fee_amount == Decimal("2.90")
        assert len(store.recorded) == 1
        assert len(bal.entries) == 1
        assert bal.entries[0].transaction_type == "fee"

    def test_no_balance_entry_without_workspace(self):
        store = _FakeFeeStore()
        bal = _FakeBalanceTransactions()
        uc = RecordPaymentFeeUseCase(fee_store=store, balance_transactions=bal)

        uc.execute(
            RecordPaymentFeeCommand(
                transaction_id=uuid4(),
                method_id=uuid4(),
                provider="stripe",
                context="shop",
                fee_amount=Decimal("1.50"),
                currency="usd",
            )
        )

        assert len(store.recorded) == 1
        assert len(bal.entries) == 0

    def test_duplicate_fee_does_not_double_debit_balance(self):
        # record_fee returns created=False (the unique constraint blocked a
        # replayed insert). The use case must NOT append a second balance debit
        # for the same gift's platform fee.
        store = _FakeFeeStore(created=False)
        bal = _FakeBalanceTransactions()
        uc = RecordPaymentFeeUseCase(fee_store=store, balance_transactions=bal)

        uc.execute(
            RecordPaymentFeeCommand(
                transaction_id=uuid4(),
                method_id=uuid4(),
                provider="stripe",
                context="revenue_share",
                fee_amount=Decimal("0.90"),
                currency="usd",
                workspace_id=uuid4(),
            )
        )

        assert len(store.recorded) == 1
        assert len(bal.entries) == 0  # no double-debit on replay

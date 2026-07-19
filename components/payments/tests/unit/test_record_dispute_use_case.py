from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from components.payments.application.use_cases.record_dispute_use_case import (
    RecordDisputeCommand,
    RecordDisputeUseCase,
)
from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity


class _FakeDisputeStore:
    def __init__(self):
        self.created = []
        self._existing = {}

    def create_dispute(self, **kwargs):
        dispute = PaymentDisputeEntity(id=uuid4(), **kwargs)
        self.created.append(dispute)
        return dispute

    def update_dispute_status(self, **kwargs):
        pass

    def find_by_external_id(self, *, provider, external_id):
        return self._existing.get((provider, external_id))


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


class TestRecordDisputeUseCase:
    def test_creates_dispute(self):
        store = _FakeDisputeStore()
        bal = _FakeBalanceTransactions()
        uc = RecordDisputeUseCase(dispute_store=store, balance_transactions=bal)

        result = uc.execute(
            RecordDisputeCommand(
                transaction_id=uuid4(),
                provider="stripe",
                status="needs_response",
                category="fraudulent",
                amount=Decimal("100.00"),
                currency="usd",
                external_id="dp_test_1",
                workspace_id=uuid4(),
            )
        )

        assert result.status == "needs_response"
        assert len(store.created) == 1
        assert len(bal.entries) == 1
        assert bal.entries[0].transaction_type == "dispute"

    def test_idempotent_on_existing(self):
        store = _FakeDisputeStore()
        existing = PaymentDisputeEntity(
            id=uuid4(),
            transaction_id=uuid4(),
            provider="stripe",
            status="needs_response",
            category="general",
            amount=Decimal("50.00"),
            currency="usd",
            external_id="dp_dup",
        )
        store._existing[("stripe", "dp_dup")] = existing
        bal = _FakeBalanceTransactions()
        uc = RecordDisputeUseCase(dispute_store=store, balance_transactions=bal)

        result = uc.execute(
            RecordDisputeCommand(
                transaction_id=uuid4(),
                provider="stripe",
                status="needs_response",
                category="general",
                amount=Decimal("50.00"),
                currency="usd",
                external_id="dp_dup",
            )
        )

        assert result.id == existing.id
        assert len(store.created) == 0
        assert len(bal.entries) == 0

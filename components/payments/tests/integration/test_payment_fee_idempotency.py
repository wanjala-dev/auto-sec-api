"""Integration: PaymentFee idempotency is DB-enforced, not read-then-write.

The revenue-share fee handler runs under ``acks_late=True`` and a single gift
fires multiple success events (checkout + charge + invoice), so the handler's
``fee_already_recorded`` pre-check is a TOCTOU under concurrent / redelivered
tasks. The real guarantee is the ``unique_payment_fee_transaction_context``
constraint on ``(transaction, context)``.

These tests prove the constraint holds even when the pre-check is bypassed: two
``record_fee`` calls for the same ``(transaction, context)`` yield exactly ONE
``PaymentFee`` row, the second returns ``created=False``, and no exception
escapes the repository.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.infrastructure.repositories.orm_payment_fee_repository import (
    OrmPaymentFeeRepository,
)
from infrastructure.persistence.workspaces.payments.models import (
    PaymentAttempt,
    PaymentFee,
    PaymentOrder,
    PaymentTransaction,
)

pytestmark = pytest.mark.django_db


def _make_transaction(workspace, method, *, amount=Decimal("25.00"), currency="USD"):
    suffix = uuid4().hex[:8]
    order = PaymentOrder.objects.create(
        workspace=workspace,
        context="workspace_support",
        status=PaymentOrder.STATUS_SUCCEEDED,
        amount=amount,
        currency=currency,
        idempotency_key=f"ord_{suffix}",
    )
    attempt = PaymentAttempt.objects.create(
        order=order,
        method=method,
        provider="stripe",
        status=PaymentAttempt.STATUS_SUCCEEDED,
        amount=amount,
        currency=currency,
        idempotency_key=f"att_{suffix}",
    )
    return PaymentTransaction.objects.create(
        attempt=attempt,
        provider="stripe",
        event_type="invoice.payment_succeeded",
        status=PaymentTransaction.STATUS_SUCCEEDED,
        amount=amount,
        currency=currency,
    )


def _record(repo, txn, method, *, context="revenue_share"):
    return repo.record_fee(
        transaction_id=txn.id,
        method_id=method.id,
        provider="stripe",
        context=context,
        fee_amount=Decimal("0.90"),
        currency="USD",
        fee_percentage=Decimal("3.0000"),
    )


class TestPaymentFeeDbIdempotency:
    def test_duplicate_insert_is_a_noop_returning_existing(
        self, workspace_factory, payment_method_factory
    ):
        ws = workspace_factory()
        method = payment_method_factory(ws)
        txn = _make_transaction(ws, method)
        repo = OrmPaymentFeeRepository()

        # First insert wins (created=True). The second simulates the pre-check
        # passing then a concurrent / redelivered duplicate insert — the unique
        # constraint blocks it, the repo catches IntegrityError and returns the
        # existing row with created=False. No exception escapes.
        first, created_first = _record(repo, txn, method)
        second, created_second = _record(repo, txn, method)

        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        assert PaymentFee.objects.filter(transaction_id=txn.id, context="revenue_share").count() == 1

    def test_distinct_context_on_same_transaction_is_allowed(
        self, workspace_factory, payment_method_factory
    ):
        # The constraint is per (transaction, context) — a different context on
        # the same transaction (e.g. a stripe processing fee vs a revenue-share
        # fee) is a legitimately distinct row.
        ws = workspace_factory()
        method = payment_method_factory(ws)
        txn = _make_transaction(ws, method)
        repo = OrmPaymentFeeRepository()

        _, created_rs = _record(repo, txn, method, context="revenue_share")
        _, created_general = _record(repo, txn, method, context="general")

        assert created_rs is True
        assert created_general is True
        assert PaymentFee.objects.filter(transaction_id=txn.id).count() == 2

from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.infrastructure.repositories.orm_payment_order_repository import (
    OrmPaymentOrderRepository,
)
from infrastructure.persistence.workspaces.payments.models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentProvider,
    WorkspacePaymentMethod,
)

pytestmark = pytest.mark.django_db


def _create_order_attempt(workspace):
    provider = PaymentProvider.objects.create(
        slug="stripe",
        display_name="Stripe",
        provider_type=PaymentProvider.API,
    )
    method = WorkspacePaymentMethod.objects.create(
        workspace=workspace,
        provider=provider,
        display_name="Stripe Method",
        status=WorkspacePaymentMethod.STATUS_ACTIVE,
    )
    order = PaymentOrder.objects.create(
        workspace=workspace,
        context="workspace_support",
        status=PaymentOrder.STATUS_PENDING,
        amount=Decimal("10.00"),
        currency="usd",
        idempotency_key="order-repo-test",
    )
    attempt = PaymentAttempt.objects.create(
        order=order,
        method=method,
        provider="stripe",
        attempt_number=1,
        status=PaymentAttempt.STATUS_CREATED,
        amount=Decimal("10.00"),
        currency="usd",
        idempotency_key="attempt-repo-test",
    )
    return order, attempt


def test_orm_payment_order_repository_marks_checkout_failed(workspace_factory):
    repository = OrmPaymentOrderRepository()
    order, attempt = _create_order_attempt(workspace_factory())

    repository.mark_checkout_failed(
        order_id=order.id,
        attempt_id=attempt.id,
        message="gateway failed",
    )

    order.refresh_from_db()
    attempt.refresh_from_db()
    assert order.status == PaymentOrder.STATUS_FAILED
    assert order.status_message == "gateway failed"
    assert attempt.status == PaymentAttempt.STATUS_FAILED
    assert attempt.status_message == "gateway failed"


def test_orm_payment_order_repository_marks_checkout_processing(workspace_factory):
    repository = OrmPaymentOrderRepository()
    order, attempt = _create_order_attempt(workspace_factory())

    repository.mark_checkout_processing(
        order_id=order.id,
        attempt_id=attempt.id,
        gateway_reference="cs_123",
        gateway_reference_type="checkout_session",
    )

    order.refresh_from_db()
    attempt.refresh_from_db()
    assert order.status == PaymentOrder.STATUS_PROCESSING
    assert attempt.status == PaymentAttempt.STATUS_PROCESSING
    assert attempt.gateway_reference == "cs_123"
    assert attempt.gateway_reference_type == "checkout_session"

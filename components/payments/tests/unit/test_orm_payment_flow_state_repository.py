from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.infrastructure.repositories.orm_payment_flow_state_repository import (
    OrmPaymentFlowStateRepository,
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
        idempotency_key="order-state-test",
    )
    attempt = PaymentAttempt.objects.create(
        order=order,
        method=method,
        provider="stripe",
        attempt_number=1,
        status=PaymentAttempt.STATUS_CREATED,
        amount=Decimal("10.00"),
        currency="usd",
        idempotency_key="attempt-state-test",
    )
    return order, attempt


def test_orm_payment_flow_state_repository_marks_failed_terminal_state(workspace_factory):
    repository = OrmPaymentFlowStateRepository()
    order, attempt = _create_order_attempt(workspace_factory())

    repository.mark_failed(
        order=order,
        attempt=attempt,
        message="gateway failed",
    )

    order.refresh_from_db()
    attempt.refresh_from_db()
    assert order.status == PaymentOrder.STATUS_FAILED
    assert order.status_message == "gateway failed"
    assert order.completed_at is not None
    assert attempt.status == PaymentAttempt.STATUS_FAILED
    assert attempt.status_message == "gateway failed"
    assert attempt.completed_at is not None


def test_orm_payment_flow_state_repository_tracks_gateway_reference(workspace_factory):
    repository = OrmPaymentFlowStateRepository()
    order, attempt = _create_order_attempt(workspace_factory())

    repository.mark_processing(
        order=order,
        attempt=attempt,
        gateway_reference="sub_123",
        gateway_reference_type="subscription",
    )

    order.refresh_from_db()
    attempt.refresh_from_db()
    assert order.status == PaymentOrder.STATUS_PROCESSING
    assert order.completed_at is None
    assert attempt.status == PaymentAttempt.STATUS_PROCESSING
    assert attempt.gateway_reference == "sub_123"
    assert attempt.gateway_reference_type == "subscription"
    assert attempt.completed_at is None

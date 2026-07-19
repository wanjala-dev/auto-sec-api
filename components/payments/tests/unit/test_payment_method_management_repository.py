from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.infrastructure.repositories.payment_method_management_repository import (
    PaymentMethodManagementRepository,
)
from infrastructure.persistence.workspaces.payments.models import (
    PaymentPlan,
    PaymentProvider,
    PaymentWebhookEndpoint,
    WorkspacePaymentMethod,
)

pytestmark = pytest.mark.django_db


def test_soft_delete_method_disables_method_plans_and_webhooks(workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
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
        enabled_contexts=[],
        is_primary=True,
    )
    plan = PaymentPlan.objects.create(
        method=method,
        context=PaymentPlan.CONTEXT_WORKSPACE_SUPPORT,
        slug="support-monthly",
        label="Support Monthly",
        amount=Decimal("10.00"),
        currency="usd",
        interval=PaymentPlan.INTERVAL_MONTH,
        is_recurring=True,
        is_active=True,
    )
    webhook = PaymentWebhookEndpoint.objects.create(
        method=method,
        name="default",
        url="https://example.com/webhook",
        signing_secret="whsec_test",
        status=PaymentWebhookEndpoint.STATUS_ACTIVE,
    )

    deleted = PaymentMethodManagementRepository().soft_delete_method(
        method_id=method.id,
        updated_by_id=owner.id,
    )

    assert deleted is True
    method.refresh_from_db()
    plan.refresh_from_db()
    webhook.refresh_from_db()

    assert method.is_deleted is True
    assert method.status == WorkspacePaymentMethod.STATUS_DISABLED
    assert method.is_primary is False
    assert method.updated_by_id == owner.id
    assert plan.is_active is False
    assert webhook.status == PaymentWebhookEndpoint.STATUS_DISABLED

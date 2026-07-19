"""Plan creation must not bypass Stripe Connect validation.

Regression: a Connect account that returned `result=success` from the OAuth
callback could still be Restricted by Stripe (`charges_enabled=False`).
The PaymentMethod is correctly persisted with status=requires_action in
that case, but PaymentPlan creation never read that flag and let plans
attach to a half-onboarded method — checkouts then succeeded at Stripe
but funds were frozen and our webhook router could not resolve the event.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from components.payments.mappers.rest.payment_serializers import PaymentPlanSerializer


_VALID_PLAN_DATA = {
    "context": "event",
    "slug": "event-donation",
    "label": "Event Donation",
    "amount": "20.00",
    "currency": "usd",
    "interval": "",
    "is_recurring": False,
    "custom_amount": False,
    "is_active": True,
}


@pytest.mark.django_db
class TestPaymentPlanSerializerActiveMethodGate:
    def test_create_blocked_when_method_requires_action(
        self, payment_method_factory, workspace_factory
    ):
        method = payment_method_factory(workspace_factory())
        method.status = "requires_action"
        method.save(update_fields=["status"])

        serializer = PaymentPlanSerializer(data=_VALID_PLAN_DATA, context={"method": method})

        with pytest.raises(ValidationError) as exc_info:
            serializer.is_valid(raise_exception=True)

        assert "method" in exc_info.value.detail
        assert "Stripe Connect onboarding" in str(exc_info.value.detail["method"][0])

    def test_create_blocked_when_method_pending(
        self, payment_method_factory, workspace_factory
    ):
        method = payment_method_factory(workspace_factory())
        method.status = "pending"
        method.save(update_fields=["status"])

        serializer = PaymentPlanSerializer(data=_VALID_PLAN_DATA, context={"method": method})

        with pytest.raises(ValidationError):
            serializer.is_valid(raise_exception=True)

    def test_create_allowed_when_method_active(
        self, payment_method_factory, workspace_factory
    ):
        method = payment_method_factory(workspace_factory())
        assert method.status == "active"

        serializer = PaymentPlanSerializer(data=_VALID_PLAN_DATA, context={"method": method})

        assert serializer.is_valid(raise_exception=False), serializer.errors

    def test_update_allowed_even_when_method_requires_action(
        self, payment_method_factory, payment_plan_factory, workspace_factory
    ):
        method = payment_method_factory(workspace_factory())
        plan = payment_plan_factory(
            method,
            context="event",
            slug="event-donation",
            label="Event Donation",
            amount=Decimal("20.00"),
            interval="",
            is_recurring=False,
            custom_amount=False,
        )
        method.status = "requires_action"
        method.save(update_fields=["status"])

        serializer = PaymentPlanSerializer(
            instance=plan,
            data={"label": "Renamed Plan"},
            context={"method": method},
            partial=True,
        )

        assert serializer.is_valid(raise_exception=False), serializer.errors

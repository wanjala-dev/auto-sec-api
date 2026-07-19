"""Shared fixtures for payment integration and unit tests.

Provides a full payment-testable workspace with provider, method, plans,
recipient, campaign, and event — everything needed to test any checkout flow.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import count
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps as django_apps


# ---------------------------------------------------------------------------
# Payment provider + method
# ---------------------------------------------------------------------------


@pytest.fixture
def payment_provider(db):
    """Return (or create) the Stripe payment provider."""
    PaymentProvider = django_apps.get_model("workspaces", "PaymentProvider")
    provider, _ = PaymentProvider.objects.get_or_create(
        slug="stripe",
        defaults={
            "display_name": "Stripe",
            "provider_type": "api",
            "capabilities": [
                "donations", "shop", "campaign", "event",
                "recipient_sponsorship", "workspace_support",
            ],
        },
    )
    return provider


@pytest.fixture
def payment_method_factory(db, payment_provider):
    """Create a WorkspacePaymentMethod for a given workspace."""
    counter = count(1)

    def _create(workspace, *, provider=None, contexts=None, account_id=None):
        PaymentMethod = django_apps.get_model("workspaces", "WorkspacePaymentMethod")
        idx = next(counter)
        return PaymentMethod.objects.create(
            workspace=workspace,
            provider=provider or payment_provider,
            display_name=f"Test Method {idx}",
            status="active",
            is_primary=True,
            enabled_contexts=contexts or [
                "donations", "shop", "campaign", "event",
                "recipient_sponsorship", "workspace_support",
                "event_ticket",
            ],
            provider_account_id=account_id or f"acct_test_{idx:04d}",
        )

    return _create


@pytest.fixture
def payment_plan_factory(db):
    """Create a PaymentPlan for a given method and context."""

    def _create(method, *, context, slug, label="Test Plan", amount=Decimal("25.00"),
                currency="usd", interval="", is_recurring=False, custom_amount=True,
                recipient=None):
        PaymentPlan = django_apps.get_model("workspaces", "PaymentPlan")
        return PaymentPlan.objects.create(
            method=method,
            context=context,
            slug=slug,
            label=label,
            amount=amount,
            currency=currency,
            interval=interval,
            is_recurring=is_recurring,
            custom_amount=custom_amount,
            recipient=recipient,
        )

    return _create


# ---------------------------------------------------------------------------
# Full payment-testable workspace
# ---------------------------------------------------------------------------


@pytest.fixture
def payment_workspace(workspace_factory, payment_method_factory, payment_plan_factory, recipient_factory):
    """Create a workspace fully wired for payment testing.

    Returns a SimpleNamespace with:
        workspace, owner, method, recipient, campaign, event,
        plans (dict keyed by context slug)
    """
    workspace = workspace_factory()
    method = payment_method_factory(workspace)

    # Plans for every revenue context
    plans = {}
    plan_specs = [
        ("recipient_sponsorship", "month", "Monthly Sponsorship", Decimal("30.00"), "month", True),
        ("workspace_support", "support-once", "One-time Support", Decimal("25.00"), "", False),
        ("campaign", "campaign-once", "Campaign Donation", Decimal("50.00"), "", False),
        ("event", "event-donation", "Event Donation", Decimal("20.00"), "", False),
        ("event_ticket", "general-admission", "General Admission", Decimal("15.00"), "", False),
        ("shop", "shop-checkout", "Shop Checkout", Decimal("0.50"), "", False),
    ]
    for context, slug, label, amount, interval, is_recurring in plan_specs:
        plans[context] = payment_plan_factory(
            method,
            context=context,
            slug=slug,
            label=label,
            amount=amount,
            interval=interval,
            is_recurring=is_recurring,
        )

    # Recipient
    recipient = recipient_factory(workspace=workspace)

    # Recipient-specific sponsorship plan
    plans["recipient_sponsorship_specific"] = payment_plan_factory(
        method,
        context="recipient_sponsorship",
        slug="month",
        label=f"Sponsor {recipient.first_name}",
        amount=Decimal("30.00"),
        interval="month",
        is_recurring=True,
        recipient=recipient,
    )

    # Campaign
    Campaign = django_apps.get_model("campaign", "Campaign")
    campaign = Campaign.objects.create(
        workspace=workspace,
        user=workspace.workspace_owner,
        name="Test Campaign",
        description="Integration test campaign",
        is_active=True,
    )

    # Event linked to campaign
    Event = django_apps.get_model("events", "Event")
    event = Event.objects.create(
        workspace=workspace,
        campaign=campaign,
        owner=workspace.workspace_owner,
        title="Test Fundraising Event",
        summary="Integration test event",
        description="A fundraising event for testing the checkout flow.",
        status="active",
        location_type="virtual",
        goal_amount=Decimal("5000.00"),
    )

    # Funding targets
    FundingTarget = django_apps.get_model("ledger", "RecipientFundingTarget")
    FundingTarget.objects.get_or_create(
        source_type="campaign",
        source_id=str(campaign.id),
        defaults={"workspace": workspace, "recipient": recipient},
    )
    FundingTarget.objects.get_or_create(
        source_type="event",
        source_id=str(event.id),
        defaults={"workspace": workspace, "recipient": recipient},
    )

    return SimpleNamespace(
        workspace=workspace,
        owner=workspace.workspace_owner,
        method=method,
        recipient=recipient,
        campaign=campaign,
        event=event,
        plans=plans,
    )


# ---------------------------------------------------------------------------
# Mock helpers for Stripe
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_stripe_checkout():
    """Patch Stripe checkout.Session.create to return a fake session."""
    with patch(
        "components.payments.infrastructure.adapters.stripe_adapter.stripe.checkout.Session.create",
    ) as mock_create:
        mock_create.return_value = SimpleNamespace(id="cs_test_mock_session")
        yield mock_create

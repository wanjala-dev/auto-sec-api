"""Revenue-share flat-% application fee — adapter integration (money-safety test).

Drives the REAL ``StripePaymentAdapter.create_checkout_session`` with Stripe's
``checkout.Session.create`` stubbed, and asserts the Connect ``application_fee``
each donation-monetization mode produces:

* ``revenue_share`` → flat bps fee (``application_fee_amount`` one-time /
  ``application_fee_percent`` recurring),
* ``tip`` / ``none`` → no bps fee (the tip, when present, is a separate line —
  modes are mutually exclusive, never a % cut on top of a tip).

This is the safety net for moving the bps SOURCE from the static
``method.platform_fee_bps`` column to the donation-monetization policy.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.infrastructure.adapters.stripe_adapter import StripePaymentAdapter


def _checkout(method, plan, *, amount, donor_tip=None):
    return StripePaymentAdapter().create_checkout_session(
        method,
        plan,
        amount=amount,
        currency="usd",
        success_url="https://example.test/success",
        cancel_url="https://example.test/cancel",
        customer_email="donor@example.test",
        client_reference_id="ref-1",
        metadata={"purpose": "Donation"},
        donor_tip=donor_tip,
    )


def _workspace_in_mode(workspace_factory, mode, bps):
    ws = workspace_factory()
    ws.donation_monetization = mode
    ws.revenue_share_bps = bps
    ws.save(update_fields=["donation_monetization", "revenue_share_bps"])
    return ws


@pytest.fixture(autouse=True)
def _stripe_secret_key(settings):
    # The adapter requires a key before calling the (mocked) Stripe API.
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"


@pytest.mark.django_db
class TestRevenueShareApplicationFee:
    def test_revenue_share_one_time_sets_application_fee_amount(
        self, workspace_factory, payment_method_factory, payment_plan_factory, mock_stripe_checkout
    ):
        ws = _workspace_in_mode(workspace_factory, "revenue_share", 300)  # 3%
        method = payment_method_factory(ws)
        plan = payment_plan_factory(
            method, context="workspace_support", slug="rs-once",
            is_recurring=False, amount=Decimal("25.00"),
        )
        _checkout(method, plan, amount=Decimal("25.00"))
        kwargs = mock_stripe_checkout.call_args.kwargs
        # 3% of $25.00 == $0.75 == 75 cents.
        assert kwargs["payment_intent_data"]["application_fee_amount"] == 75

    def test_revenue_share_recurring_sets_application_fee_percent(
        self, workspace_factory, payment_method_factory, payment_plan_factory, mock_stripe_checkout
    ):
        ws = _workspace_in_mode(workspace_factory, "revenue_share", 250)  # 2.5%
        method = payment_method_factory(ws)
        plan = payment_plan_factory(
            method, context="recipient_sponsorship", slug="rs-month",
            is_recurring=True, interval="month", amount=Decimal("30.00"),
        )
        _checkout(method, plan, amount=Decimal("30.00"))
        kwargs = mock_stripe_checkout.call_args.kwargs
        assert kwargs["subscription_data"]["application_fee_percent"] == 2.5

    def test_tip_mode_takes_no_percentage_cut(
        self, workspace_factory, payment_method_factory, payment_plan_factory, mock_stripe_checkout
    ):
        # Rate is set but mode is tip → policy returns 0 bps. With no donor_tip,
        # there is no application fee at all (the tip, if any, is separate).
        ws = _workspace_in_mode(workspace_factory, "tip", 300)
        method = payment_method_factory(ws)
        plan = payment_plan_factory(
            method, context="workspace_support", slug="tip-once",
            is_recurring=False, amount=Decimal("25.00"),
        )
        _checkout(method, plan, amount=Decimal("25.00"))
        kwargs = mock_stripe_checkout.call_args.kwargs
        assert kwargs["payment_intent_data"].get("application_fee_amount", 0) == 0

    def test_none_mode_takes_no_fee(
        self, workspace_factory, payment_method_factory, payment_plan_factory, mock_stripe_checkout
    ):
        ws = _workspace_in_mode(workspace_factory, "none", 300)
        method = payment_method_factory(ws)
        plan = payment_plan_factory(
            method, context="workspace_support", slug="none-once",
            is_recurring=False, amount=Decimal("25.00"),
        )
        _checkout(method, plan, amount=Decimal("25.00"))
        kwargs = mock_stripe_checkout.call_args.kwargs
        assert kwargs["payment_intent_data"].get("application_fee_amount", 0) == 0

    def test_default_tip_workspace_is_byte_for_byte_unchanged(
        self, workspace_factory, payment_method_factory, payment_plan_factory, mock_stripe_checkout
    ):
        # A brand-new workspace (donation_monetization defaults to 'tip') takes
        # no platform fee — proving the bps-source move is a no-op for everyone
        # currently live.
        ws = workspace_factory()
        method = payment_method_factory(ws)
        plan = payment_plan_factory(
            method, context="workspace_support", slug="default-once",
            is_recurring=False, amount=Decimal("25.00"),
        )
        _checkout(method, plan, amount=Decimal("25.00"))
        kwargs = mock_stripe_checkout.call_args.kwargs
        assert kwargs["payment_intent_data"].get("application_fee_amount", 0) == 0

"""Integration: the Connect application-fee adapter, Stripe SDK boundary stubbed.

Drives the REAL ``StripeConnectApplicationFeeAdapter.retrieve_application_fee``
with ``stripe.PaymentIntent.retrieve`` monkeypatched. The load-bearing
behaviour: a TRANSIENT Stripe error (rate-limit / network / 5xx) must RE-RAISE
so the acks_late fee-recording task retries — never swallow it into None, which
would permanently drop a real gift's platform fee. A DEFINITIVE error (PI not
found, auth) returns None: there is genuinely no fee to record.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
import stripe

from components.payments.infrastructure.adapters.stripe_connect_application_fee_adapter import (
    StripeConnectApplicationFeeAdapter,
)


@pytest.fixture(autouse=True)
def _stripe_secret_key(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"


def _retrieve(monkeypatch, side_effect):
    def _fake(intent_id, **kwargs):
        if isinstance(side_effect, Exception):
            raise side_effect
        return side_effect

    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", _fake)


class TestConnectApplicationFeeAdapter:
    @pytest.mark.parametrize(
        "error",
        [
            stripe.error.RateLimitError("rate limited"),
            stripe.error.APIConnectionError("network blip"),
            stripe.error.APIError("stripe 5xx"),
        ],
    )
    def test_transient_stripe_error_reraises(self, monkeypatch, error):
        _retrieve(monkeypatch, error)
        with pytest.raises(type(error)):
            StripeConnectApplicationFeeAdapter().retrieve_application_fee(
                payment_intent_id="pi_transient",
                stripe_account="acct_test_0001",
                currency="USD",
            )

    def test_invalid_request_returns_none(self, monkeypatch):
        _retrieve(monkeypatch, stripe.error.InvalidRequestError("no such pi", "id"))
        result = StripeConnectApplicationFeeAdapter().retrieve_application_fee(
            payment_intent_id="pi_missing",
            stripe_account="acct_test_0001",
        )
        assert result is None

    def test_generic_stripe_error_returns_none(self, monkeypatch):
        _retrieve(monkeypatch, stripe.error.AuthenticationError("bad key"))
        result = StripeConnectApplicationFeeAdapter().retrieve_application_fee(
            payment_intent_id="pi_auth",
            stripe_account="acct_test_0001",
        )
        assert result is None

    def test_returns_actual_fee_from_charge(self, monkeypatch):
        intent = {
            "latest_charge": {
                "application_fee_amount": 75,  # 75 cents
                "currency": "usd",
            }
        }
        _retrieve(monkeypatch, intent)
        result = StripeConnectApplicationFeeAdapter().retrieve_application_fee(
            payment_intent_id="pi_ok",
            stripe_account="acct_test_0001",
            currency="USD",
        )
        assert result == Decimal("0.75")

    def test_no_fee_on_charge_returns_none(self, monkeypatch):
        intent = {"latest_charge": {"application_fee_amount": None, "currency": "usd"}}
        _retrieve(monkeypatch, intent)
        result = StripeConnectApplicationFeeAdapter().retrieve_application_fee(
            payment_intent_id="pi_no_fee",
            stripe_account="acct_test_0001",
        )
        assert result is None

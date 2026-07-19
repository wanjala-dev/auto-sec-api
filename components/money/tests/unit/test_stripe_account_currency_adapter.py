"""Unit tests for the real StripeAccountCurrencyAdapter.

Stripe is not actually called — we patch ``stripe.Account.retrieve``.
These tests cover the three branches the backfill command depends on:

- happy path: Stripe returns ``default_currency`` → we upper-case it.
- empty input: adapter returns None without touching Stripe.
- Stripe error / missing key: adapter returns None rather than raising.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from components.money.infrastructure.adapters.stripe_account_currency_adapter import (
    StripeAccountCurrencyAdapter,
)


class _FakeAccount:
    def __init__(self, default_currency):
        self.default_currency = default_currency


class TestStripeAccountCurrencyAdapter:
    def test_empty_account_id_returns_none_without_stripe_call(self):
        adapter = StripeAccountCurrencyAdapter()
        with patch("stripe.Account.retrieve") as retrieve:
            assert adapter.resolve_default_currency("") is None
            retrieve.assert_not_called()

    def test_returns_uppercase_default_currency(self, settings):
        settings.STRIPE_SECRET_KEY = "sk_test_fake"
        adapter = StripeAccountCurrencyAdapter()
        with patch(
            "stripe.Account.retrieve",
            return_value=_FakeAccount("cad"),
        ) as retrieve:
            result = adapter.resolve_default_currency("acct_123")
        assert result == "CAD"
        retrieve.assert_called_once_with("acct_123", api_key="sk_test_fake")

    def test_returns_none_when_account_has_no_default_currency(self, settings):
        settings.STRIPE_SECRET_KEY = "sk_test_fake"
        adapter = StripeAccountCurrencyAdapter()
        with patch(
            "stripe.Account.retrieve",
            return_value=_FakeAccount(None),
        ):
            assert adapter.resolve_default_currency("acct_123") is None

    def test_returns_none_on_stripe_error(self, settings):
        import stripe

        settings.STRIPE_SECRET_KEY = "sk_test_fake"
        adapter = StripeAccountCurrencyAdapter()
        with patch(
            "stripe.Account.retrieve",
            side_effect=stripe.error.InvalidRequestError("boom", "account"),
        ):
            assert adapter.resolve_default_currency("acct_123") is None

    def test_returns_none_when_no_api_key_configured(self, settings):
        # Clearing both keys should short-circuit without attempting
        # a Stripe call — prevents leaking a blank auth header.
        settings.STRIPE_SECRET_KEY = ""
        if hasattr(settings, "STRIPE_API_KEY"):
            settings.STRIPE_API_KEY = ""
        adapter = StripeAccountCurrencyAdapter()
        with patch("stripe.Account.retrieve") as retrieve:
            assert adapter.resolve_default_currency("acct_123") is None
            retrieve.assert_not_called()


pytestmark = pytest.mark.django_db(transaction=False)

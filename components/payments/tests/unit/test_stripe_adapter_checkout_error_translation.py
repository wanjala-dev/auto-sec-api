"""Regression tests for Stripe checkout-session error translation.

Production bug: a Stripe checkout against a connected account that is
revoked / not-onboarded / nonexistent raised an unhandled
``stripe.error.PermissionError``, which bubbled out of the adapter all the
way to DRF as an HTTP 500 to the donor. Any org whose Stripe Connect
account is revoked or mis-onboarded would 500 a real donor's checkout.

Fix: ``StripePaymentAdapter.create_checkout_session`` now wraps the
``stripe.checkout.Session.create`` call and translates raw Stripe SDK
errors into typed payments domain errors via
``_translate_stripe_checkout_error``:

- ``PermissionError`` / ``AuthenticationError`` → ``PaymentAccountUnavailableError``
  (a ``ValidationError`` → HTTP 400), donor-safe message, no secret/account leak.
- ``CardError`` → ``PaymentValidationError`` (→ 400) carrying ``user_message``.
- ``InvalidRequestError`` → ``PaymentValidationError`` (→ 400).
- ``RateLimitError`` / ``APIConnectionError`` / ``APIError`` / other
  ``StripeError`` → ``ProviderUnavailableError`` (an ``IntegrationError`` → 502).

These tests stub ``stripe.checkout.Session.create`` at the SDK boundary —
no DB, no live Stripe.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe
from django.test import override_settings

from components.payments.domain.errors import (
    PaymentAccountUnavailableError,
    PaymentValidationError,
    ProviderUnavailableError,
)
from components.payments.infrastructure.adapters.stripe_adapter import StripePaymentAdapter
from components.shared_kernel.domain.errors import IntegrationError, ValidationError

# Values that MUST never leak into a user-facing message.
_SECRET_KEY = "sk_test_super_secret_key_prefix_visible_in_stripe_error"
_ACCOUNT_ID = "acct_revoked_or_nonexistent_001"


def _build_method():
    """Minimal WorkspacePaymentMethod stand-in the adapter reads."""
    return SimpleNamespace(
        id="pm-checkout-error",
        provider=SimpleNamespace(slug="stripe"),
        provider_account_id=_ACCOUNT_ID,
        workspace_id="ws-checkout-error",
        workspace=SimpleNamespace(
            donation_monetization=None,
            revenue_share_bps=0,
        ),
        display_name="Demo Org Donations",
        # decrypt_json("") returns {} → falls back to STRIPE_SECRET_KEY.
        encrypted_credentials="",
    )


def _create_checkout(monkeypatch, raising_exc):
    """Drive create_checkout_session with Session.create raising `raising_exc`."""

    def _raise(**kwargs):
        raise raising_exc

    monkeypatch.setattr(stripe.checkout.Session, "create", _raise)

    return StripePaymentAdapter().create_checkout_session(
        _build_method(),
        None,  # no plan — one-time payment
        amount=Decimal("25.00"),
        currency="usd",
        success_url="https://example.test/success",
        cancel_url="https://example.test/cancel",
        customer_email="donor@example.test",
        client_reference_id="ref-001",
        metadata={"purpose": "Sponsor a recipient"},
    )


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_permission_error_maps_to_account_unavailable_400_class(monkeypatch):
    exc = stripe.error.PermissionError(
        f"The provided key '{_SECRET_KEY}' does not have access to account "
        f"'{_ACCOUNT_ID}' (or that account does not exist). "
        "Application access may have been revoked."
    )
    with pytest.raises(PaymentAccountUnavailableError) as caught:
        _create_checkout(monkeypatch, exc)

    err = caught.value
    # ValidationError-based → HTTP 400 via the exception handler.
    assert isinstance(err, ValidationError)
    assert not isinstance(err, IntegrationError)
    # The donor-safe message must NOT leak the secret key or the account id.
    message = str(err)
    assert _SECRET_KEY not in message
    assert _ACCOUNT_ID not in message
    assert "sk_test" not in message
    assert "acct_" not in message


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_authentication_error_maps_to_account_unavailable_400_class(monkeypatch):
    exc = stripe.error.AuthenticationError(
        f"Invalid API Key provided: {_SECRET_KEY}"
    )
    with pytest.raises(PaymentAccountUnavailableError) as caught:
        _create_checkout(monkeypatch, exc)
    assert isinstance(caught.value, ValidationError)
    assert _SECRET_KEY not in str(caught.value)


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_card_error_maps_to_validation_error_with_user_message(monkeypatch):
    # Stripe's CardError.user_message is the donor-facing copy (derived from
    # the `message` arg in this SDK version). We surface it verbatim.
    exc = stripe.error.CardError(
        message="Your card was declined.",
        param="number",
        code="card_declined",
    )

    with pytest.raises(PaymentValidationError) as caught:
        _create_checkout(monkeypatch, exc)

    err = caught.value
    assert isinstance(err, ValidationError)
    assert not isinstance(err, IntegrationError)
    assert str(err) == "Your card was declined."


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_card_error_without_user_message_falls_back(monkeypatch):
    # Empty user_message → adapter falls back to a generic donor-safe line.
    exc = stripe.error.CardError(
        message="",
        param="number",
        code="card_declined",
    )

    with pytest.raises(PaymentValidationError) as caught:
        _create_checkout(monkeypatch, exc)
    assert str(caught.value) == "Your card was declined."


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_invalid_request_error_maps_to_validation_error(monkeypatch):
    exc = stripe.error.InvalidRequestError(
        message="Received unknown parameter: foo",
        param="foo",
    )
    with pytest.raises(PaymentValidationError) as caught:
        _create_checkout(monkeypatch, exc)

    err = caught.value
    assert isinstance(err, ValidationError)
    assert not isinstance(err, IntegrationError)
    # Generic, donor-safe — does not echo the raw Stripe param/message.
    assert "foo" not in str(err)


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_rate_limit_error_maps_to_provider_unavailable_502_class(monkeypatch):
    exc = stripe.error.RateLimitError("Too many requests")
    with pytest.raises(ProviderUnavailableError) as caught:
        _create_checkout(monkeypatch, exc)

    err = caught.value
    # IntegrationError-based → HTTP 502, retryable, counts toward breaker.
    assert isinstance(err, IntegrationError)
    assert not isinstance(err, ValidationError)


@override_settings(STRIPE_SECRET_KEY=_SECRET_KEY)
def test_api_connection_error_maps_to_provider_unavailable(monkeypatch):
    exc = stripe.error.APIConnectionError("Network is down")
    with pytest.raises(ProviderUnavailableError) as caught:
        _create_checkout(monkeypatch, exc)
    assert isinstance(caught.value, IntegrationError)

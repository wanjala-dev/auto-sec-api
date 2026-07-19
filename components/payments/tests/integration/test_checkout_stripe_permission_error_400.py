"""Integration regression: a Stripe PermissionError on checkout → HTTP 400, not 500.

Production bug: a recipient-sponsorship checkout against a connected account
that is revoked / not-onboarded / nonexistent raised an unhandled
``stripe.error.PermissionError`` which DRF surfaced as a 500 to the donor.
The frontend treats >= 500 as "backend unhealthy" and blacks out the app, so
one org's bad Stripe account could black out every donor's session.

This drives the actual bug-repro endpoint — ``POST /sponsorship/sponsor/``
with a one-time ``custom_amount`` (the simplest gateway path, reaching
``Session.create`` directly) — with ``stripe.checkout.Session.create`` stubbed
to raise ``PermissionError`` at the SDK boundary, and asserts the controller
returns **400** with a donor-safe message that leaks neither the secret key
nor the connected-account id.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe

# The leak-bait values: the raw Stripe message embeds both.
_SECRET_KEY = "sk_test_leakcheck_secret"
_ACCOUNT_ID = "acct_revoked_leakcheck_001"

STRIPE_CREATE = (
    "components.payments.infrastructure.adapters.stripe_adapter.stripe.checkout.Session.create"
)


@pytest.fixture(autouse=True)
def _stripe_test_key(settings):
    settings.STRIPE_SECRET_KEY = _SECRET_KEY


@pytest.fixture
def pw(workspace_factory, recipient_factory, api_client):
    from infrastructure.persistence.workspaces.payments.models import (
        PaymentProvider,
        WorkspacePaymentMethod,
    )

    workspace = workspace_factory()
    recipient = recipient_factory(workspace=workspace)

    provider = PaymentProvider.objects.first() or PaymentProvider.objects.create(
        slug="stripe", provider_type="api", is_active=True,
    )
    method = WorkspacePaymentMethod.objects.create(
        workspace=workspace,
        provider=provider,
        status="active",
        provider_account_id=_ACCOUNT_ID,
    )

    api_client.force_authenticate(user=workspace.workspace_owner)
    return SimpleNamespace(workspace=workspace, method=method, recipient=recipient)


@pytest.mark.django_db
def test_revoked_account_checkout_returns_400_not_500(api_client, pw):
    permission_error = stripe.error.PermissionError(
        f"The provided key '{_SECRET_KEY}' does not have access to account "
        f"'{_ACCOUNT_ID}' (or that account does not exist). "
        "Application access may have been revoked."
    )

    with patch(STRIPE_CREATE, side_effect=permission_error):
        response = api_client.post(
            "/sponsorship/sponsor/",
            {
                "recipient_id": str(pw.recipient.id),
                "name": "Donor",
                "email": "donor@test.com",
                "custom_amount": "25",
                "payment_method_id": str(pw.method.id),
            },
            format="json",
        )

    # The whole point: a clean, handled 400 — never a 500.
    assert response.status_code == 400, response.data

    # Proves the 400 came from the Stripe-error translation (not some other
    # validation path): the exception handler stamps the domain error class.
    assert response.data.get("error_code") == "PaymentAccountUnavailableError"

    blob = str(response.data)
    # Donor-safe message — no secret key, no internal account id.
    assert _SECRET_KEY not in blob
    assert _ACCOUNT_ID not in blob
    assert "sk_test" not in blob
    assert "acct_" not in blob

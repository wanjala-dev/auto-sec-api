"""End-to-end signed-payload test for the team-plan billing webhook.

Mirrors ``test_stripe_webhook_signed_e2e.py`` for the SaaS-billing webhook
URL ``/workspaces/payments/stripe/webhook/``. The team-plan flow handles
your platform's own subscription revenue (charges workspace admins per
team size); losing webhook events here means losing real revenue tracking.

Key difference from the donation e2e tests: team-plan verification reads
``STRIPE_WEBHOOK_KEY`` as the primary global secret and falls back to
``STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET`` only when the primary is empty
(see ``components/payments/infrastructure/adapters/stripe_adapter.py``
``verify_webhook`` for ``endpoint_name="team_subscriptions"``). The tests
override BOTH so the verify path is fully under our control — overriding
only the subscriptions secret would silently fall through to the real
``STRIPE_WEBHOOK_KEY`` and fail verification.
"""
from __future__ import annotations

import json

import pytest
from django.test import override_settings

from components.payments.tests._helpers.stripe_webhook_signing import (
    make_event,
    stripe_signed_headers,
)
from infrastructure.persistence.workspaces.payments.models import PaymentEvent


WEBHOOK_PATH = "/workspaces/billing/stripe/webhook/"
TEST_SECRET = "whsec_test_team_plan_e2e_only"
WRONG_SECRET = "whsec_wrong_team_plan_secret"


def _subscription_event(event_id: str) -> dict:
    """A minimal ``customer.subscription.created`` payload.

    Picked because it's the safest event for team-plan e2e: the live
    handler ignores it (no fixture set-up needed) but the verification
    + idempotency-ledger pipeline still runs end-to-end, which is what
    these tests prove.
    """
    return make_event(
        event_id=event_id,
        event_type="customer.subscription.created",
        data_object={
            "id": "sub_test_e2e_subscription",
            "object": "subscription",
            "status": "active",
            "metadata": {},
        },
    )


@pytest.mark.django_db
@override_settings(
    STRIPE_WEBHOOK_KEY="",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET=TEST_SECRET,
    # The handler resolves a Stripe API key (method credentials → settings)
    # before processing; test settings leave STRIPE_SECRET_KEY empty, so
    # provide a dummy test key for the signature-verification path.
    STRIPE_SECRET_KEY="sk_test_team_plan_e2e_only",
)
def test_team_plan_webhook_accepts_signed_payload_and_records_event(api_client):
    payload = json.dumps(_subscription_event("evt_team_plan_signed_001")).encode("utf-8")
    headers = stripe_signed_headers(payload, TEST_SECRET)

    response = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content
    assert PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_team_plan_signed_001"
    ).exists()


@pytest.mark.django_db
@override_settings(
    STRIPE_WEBHOOK_KEY="",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET=TEST_SECRET,
    # The handler resolves a Stripe API key (method credentials → settings)
    # before processing; test settings leave STRIPE_SECRET_KEY empty, so
    # provide a dummy test key for the signature-verification path.
    STRIPE_SECRET_KEY="sk_test_team_plan_e2e_only",
)
def test_team_plan_webhook_idempotent_on_duplicate_delivery(api_client):
    payload = json.dumps(_subscription_event("evt_team_plan_dup_001")).encode("utf-8")

    # First delivery.
    r1 = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **stripe_signed_headers(payload, TEST_SECRET),
    )
    assert r1.status_code == 200, r1.content

    # Stripe retry — same event_id, fresh signature timestamp.
    r2 = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **stripe_signed_headers(payload, TEST_SECRET),
    )
    assert r2.status_code == 200, r2.content

    rows = PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_team_plan_dup_001"
    )
    assert rows.count() == 1, (
        f"expected exactly one ledger row after duplicate delivery, got {rows.count()}"
    )


@pytest.mark.django_db
@override_settings(
    STRIPE_WEBHOOK_KEY="",
    STRIPE_CONNECT_WEBHOOK_SECRET="",
    STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET=TEST_SECRET,
    # The handler resolves a Stripe API key (method credentials → settings)
    # before processing; test settings leave STRIPE_SECRET_KEY empty, so
    # provide a dummy test key for the signature-verification path.
    STRIPE_SECRET_KEY="sk_test_team_plan_e2e_only",
)
def test_team_plan_webhook_rejects_invalid_signature(api_client):
    payload = json.dumps(_subscription_event("evt_team_plan_bad_sig_001")).encode("utf-8")
    # Sign with the wrong secret. Stripe SDK construct_event must reject it.
    headers = stripe_signed_headers(payload, WRONG_SECRET)

    response = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert response.status_code in (400, 401, 403), response.content
    assert not PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_team_plan_bad_sig_001"
    ).exists()

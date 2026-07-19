"""End-to-end Stripe webhook test using real signed payloads.

The pre-existing webhook tests (`test_payments_webhook_idempotency.py`) mock
`StripePaymentAdapter.verify_webhook` with a stub that just returns the event,
which means signature verification has zero coverage. If `stripe.Webhook
.construct_event` ever changes API, or if our header parsing breaks, those
tests would not catch it.

This module signs payloads exactly the way Stripe does and POSTs them to the
live URL pattern (`/sponsorship/donations/stripe/webhook/`). Three things
get asserted on every test:

1. **Verification path**: a payload signed with the configured Stripe
   webhook secret returns 200.
2. **Idempotency**: POSTing the *same* event twice produces only one
   `PaymentEvent` ledger row (the unique constraint on
   ``provider, event_id`` does the dedupe).
3. **Invalid signature**: a payload signed with the wrong secret is
   rejected by ``stripe.Webhook.construct_event`` and the controller
   returns a 4xx.
"""
from __future__ import annotations

import json

import pytest
from django.test import override_settings

from components.payments.tests._helpers.stripe_webhook_signing import (
    make_event as _make_event,
    stripe_signed_headers as _stripe_signed_headers,
)
from infrastructure.persistence.workspaces.payments.models import PaymentEvent


WEBHOOK_PATH = "/sponsorship/donations/stripe/webhook/"
TEST_SECRET = "whsec_test_signing_secret_for_e2e_only"
WRONG_SECRET = "whsec_wrong_secret_for_negative_test"


@pytest.mark.django_db
@override_settings(STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET=TEST_SECRET)
def test_stripe_webhook_accepts_signed_payload_and_records_event(api_client):
    payload = json.dumps(_make_event("evt_test_signed_001")).encode("utf-8")
    headers = _stripe_signed_headers(payload, TEST_SECRET)

    response = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content
    assert PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_test_signed_001"
    ).exists()


@pytest.mark.django_db
@override_settings(STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET=TEST_SECRET)
def test_stripe_webhook_idempotent_on_duplicate_delivery(api_client):
    payload = json.dumps(_make_event("evt_test_dup_001")).encode("utf-8")

    # First delivery: real Stripe → us
    headers_1 = _stripe_signed_headers(payload, TEST_SECRET)
    r1 = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers_1,
    )
    assert r1.status_code == 200, r1.content

    # Second delivery: Stripe retry on the same event id (it re-signs with
    # a fresh timestamp, so we mint new headers — the event id is what the
    # idempotency layer keys on, not the signature).
    headers_2 = _stripe_signed_headers(payload, TEST_SECRET)
    r2 = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers_2,
    )
    assert r2.status_code == 200, r2.content

    rows = PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_test_dup_001"
    )
    assert rows.count() == 1, (
        f"expected exactly one ledger row after duplicate delivery, got {rows.count()}"
    )


@pytest.mark.django_db
@override_settings(STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET=TEST_SECRET)
def test_stripe_webhook_rejects_invalid_signature(api_client):
    payload = json.dumps(_make_event("evt_test_bad_sig_001")).encode("utf-8")
    # Sign with the wrong secret. construct_event must reject it.
    headers = _stripe_signed_headers(payload, WRONG_SECRET)

    response = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert response.status_code in (400, 401, 403), response.content
    assert not PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_test_bad_sig_001"
    ).exists()

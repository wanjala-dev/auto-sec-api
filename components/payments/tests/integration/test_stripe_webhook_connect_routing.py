"""End-to-end test that Stripe Connect webhooks route to the workspace
named in ``event.account``, not to whichever method's webhook secret
happened to verify the signature first.

Regression: in prod, two `WorkspacePaymentMethod` rows on different
workspaces shared a Connect signing secret (Stripe signs every event
delivered to a single platform endpoint with the same secret). The
verifier iterated methods, matched against whichever secret crawled
first, and returned that method as authoritative — even when its
``provider_account_id`` did not match ``event.account`` in the payload.
The downstream Stripe API call (using the wrong method's
``provider_account_id`` as ``stripe_account``) 404'd, the PaymentEvent
got attributed to the wrong workspace, and the originating workspace's
PaymentAttempt sat in ``processing`` forever.

This test posts a signed Connect webhook through the full controller
path and asserts the resulting `PaymentEvent` is attributed to the
workspace whose method matches `event.account`, regardless of the
order in which methods are iterated.
"""
from __future__ import annotations

import json

import pytest
from django.test import override_settings

from components.payments.tests._helpers.stripe_webhook_signing import (
    make_event as _make_event,
    stripe_signed_headers as _stripe_signed_headers,
)
from infrastructure.persistence.workspaces.payments.models import (
    PaymentEvent,
    PaymentWebhookEndpoint,
)


WEBHOOK_PATH = "/sponsorship/donations/stripe/webhook/"
SHARED_SECRET = "whsec_shared_connect_secret_for_routing_test"


@pytest.mark.django_db
@override_settings(STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET=SHARED_SECRET)
def test_connect_webhook_routes_by_event_account_when_secret_is_shared(
    api_client, workspace_factory, payment_method_factory
):
    """Two methods on different workspaces share a signing secret. A
    Connect event names one of them via ``event.account``. The
    PaymentEvent must be attributed to that workspace, not the one
    whose method was iterated first.
    """
    target_account = "acct_target_routing_001"
    absorbing_account = "acct_absorbing_routing_001"

    target_workspace = workspace_factory()
    absorbing_workspace = workspace_factory()

    target_method = payment_method_factory(
        target_workspace, account_id=target_account
    )
    absorbing_method = payment_method_factory(
        absorbing_workspace, account_id=absorbing_account
    )

    # Both methods carry a webhook with the SAME signing secret — that's
    # the production reality: one platform Connect endpoint, one
    # secret, multiple methods recording it. Without the verifier fix,
    # the first match wins and the wrong workspace gets the event.
    for method in (absorbing_method, target_method):
        PaymentWebhookEndpoint.objects.create(
            method=method,
            name="donations",
            url="https://example.test/sponsorship/donations/stripe/webhook/",
            signing_secret=SHARED_SECRET,
            status=PaymentWebhookEndpoint.STATUS_ACTIVE,
        )

    event = _make_event("evt_routing_e2e_001")
    event["account"] = target_account
    payload = json.dumps(event).encode("utf-8")
    headers = _stripe_signed_headers(payload, SHARED_SECRET)

    response = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content

    payment_event = PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_routing_e2e_001"
    ).first()
    assert payment_event is not None, "no PaymentEvent recorded for the webhook"
    assert str(payment_event.workspace_id) == str(target_workspace.id), (
        f"PaymentEvent attributed to {payment_event.workspace_id}, "
        f"expected target workspace {target_workspace.id}"
    )
    assert payment_event.provider_account_id == target_account


@pytest.mark.django_db
@override_settings(STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET=SHARED_SECRET)
def test_connect_webhook_for_unknown_account_does_not_misattribute(
    api_client, workspace_factory, payment_method_factory
):
    """When ``event.account`` names a connected account we don't have
    a method for, the PaymentEvent should still record (so we have an
    audit trail) but must NOT be attributed to the absorbing
    workspace.
    """
    absorbing_account = "acct_absorbing_unknown_001"
    unknown_account = "acct_we_have_no_method_for_001"

    absorbing_workspace = workspace_factory()
    absorbing_method = payment_method_factory(
        absorbing_workspace, account_id=absorbing_account
    )
    PaymentWebhookEndpoint.objects.create(
        method=absorbing_method,
        name="donations",
        url="https://example.test/sponsorship/donations/stripe/webhook/",
        signing_secret=SHARED_SECRET,
        status=PaymentWebhookEndpoint.STATUS_ACTIVE,
    )

    event = _make_event("evt_routing_e2e_unknown_001")
    event["account"] = unknown_account
    payload = json.dumps(event).encode("utf-8")
    headers = _stripe_signed_headers(payload, SHARED_SECRET)

    response = api_client.post(
        WEBHOOK_PATH,
        data=payload,
        content_type="application/json",
        **headers,
    )

    # The webhook signature verifies, so we still 200 the request and
    # record an audit row — but with the absorbing workspace NOT
    # claiming the event.
    assert response.status_code == 200, response.content

    payment_event = PaymentEvent.objects.filter(
        provider="stripe", event_id="evt_routing_e2e_unknown_001"
    ).first()
    assert payment_event is not None
    assert str(payment_event.workspace_id) != str(absorbing_workspace.id), (
        "PaymentEvent must not be misattributed to the absorbing workspace"
    )
    assert payment_event.provider_account_id == unknown_account

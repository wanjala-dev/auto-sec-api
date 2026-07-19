"""Shared helpers for end-to-end Stripe webhook tests.

Both the donation webhook tests (``test_stripe_webhook_signed_e2e.py``) and
the team-plan billing webhook tests
(``test_stripe_team_plan_webhook_signed_e2e.py``) sign payloads with the
exact format Stripe uses and POST them to the live URL pattern. The signing
+ payload-construction helpers live here so they don't drift between the
two test modules.

Stripe's signature header format: ``t=<unix_ts>,v1=<hex_sig>`` where
``sig = HMAC-SHA256(secret, f"{ts}.{payload}")``. Anything else gets
rejected by ``stripe.Webhook.construct_event``, which is exactly what
we want the negative-path test to exercise.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any


def stripe_signed_headers(payload_bytes: bytes, secret: str) -> dict[str, str]:
    """Build a ``Stripe-Signature`` header for a payload + secret pair.

    Returns a kwargs dict that can be splatted into Django's test client
    ``post(..., **headers)``.
    """
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload_bytes.decode('utf-8')}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "HTTP_STRIPE_SIGNATURE": f"t={timestamp},v1={signature}",
    }


def make_event(
    event_id: str,
    event_type: str = "checkout.session.expired",
    data_object: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal Stripe-shaped event payload.

    The default ``checkout.session.expired`` is the safest event type for
    a donation-flow e2e test because the recipient sponsorship lifecycle
    handler short-circuits when there's no matching order — no DB rows
    beyond the PaymentEvent are touched, so the test stays focused on
    signature/idempotency rather than needing a sponsorship fixture.

    Tests for the team-plan flow override this with
    ``customer.subscription.created`` for the same reason: the team-plan
    handler ignores it (no fixture set up needed) but verification +
    idempotency-ledger insertion still run end-to-end.
    """
    if data_object is None:
        data_object = {
            "id": "cs_test_e2e_session",
            "object": "checkout.session",
            "metadata": {},
        }
    return {
        "id": event_id,
        "object": "event",
        "api_version": "2024-04-10",
        "created": int(time.time()),
        "type": event_type,
        "livemode": False,
        "pending_webhooks": 1,
        "request": {"id": None, "idempotency_key": None},
        "data": {"object": data_object},
    }

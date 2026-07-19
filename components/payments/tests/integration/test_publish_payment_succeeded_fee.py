"""Unit: _publish_payment_succeeded copies the actual application fee.

Charge / invoice payloads carry ``application_fee_amount`` at the top level of
the object; the publisher must lift it onto the PaymentSucceeded event so the
fee handler records what Stripe actually took. The one-time checkout payload
carries no fee — there it stays "0".
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from infrastructure.persistence.workspaces.payments.models import PaymentEvent

pytestmark = pytest.mark.django_db


def _capture_published(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "components.shared_kernel.infrastructure.adapters.celery_event_publisher."
        "CeleryEventPublisher.publish",
        lambda self, event: captured.append(event),
    )
    return captured


def _publish_for(payload, *, event_type, monkeypatch):
    """Invoke the publisher directly via the success-update path.

    ``_publish_payment_succeeded`` registers its emit on ``transaction.on_commit``;
    we run it inside an atomic block whose commit callbacks we capture, so the
    emit actually fires within the test transaction.
    """
    captured = _capture_published(monkeypatch)
    event = PaymentEvent.objects.create(
        provider="stripe",
        event_id=f"evt_{event_type}",
        event_type=event_type,
        amount=Decimal("25.00"),
        currency="USD",
        payload=payload,
    )
    from django.test import TestCase

    from components.payments.infrastructure.adapters import payment_event_state

    # _publish_payment_succeeded queues its emit on transaction.on_commit;
    # capture + execute the callbacks so the emit fires inside the test.
    with TestCase.captureOnCommitCallbacks(using="default", execute=True):
        payment_event_state._publish_payment_succeeded(event)
    return captured


def test_invoice_fee_lifted_onto_event(monkeypatch):
    payload = {
        "data": {"object": {
            "metadata": {"context": "workspace_support", "email": "d@e.test"},
            "application_fee_amount": 90,
        }},
        "type": "invoice.payment_succeeded",
    }
    captured = _publish_for(
        payload, event_type="invoice.payment_succeeded", monkeypatch=monkeypatch
    )
    assert len(captured) == 1
    assert captured[0].application_fee_amount == "90"


def test_checkout_session_has_no_fee(monkeypatch):
    payload = {
        "data": {"object": {
            "metadata": {"context": "workspace_support", "email": "d@e.test"},
            "payment_intent": "pi_1",
        }},
        "type": "checkout.session.completed",
    }
    captured = _publish_for(
        payload, event_type="checkout.session.completed", monkeypatch=monkeypatch
    )
    assert len(captured) == 1
    assert captured[0].application_fee_amount == "0"

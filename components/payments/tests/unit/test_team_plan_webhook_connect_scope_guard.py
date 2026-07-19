"""Regression tests for the Connect/platform webhook scope guard.

The platform/team billing webhook handler (`TeamPlanWebhookRepository`) must
never process a Stripe **Connect** event — one carrying a top-level ``account``.
If it did, two things break:

1. It would record/claim the event in the shared ``PaymentEvent`` idempotency
   table (keyed by ``event_id``), making the correct Connect/donations endpoint
   dedupe-skip the same event so a recurring sponsorship invoice never books a
   ``Donation`` (the recipient's balance silently stays at $0).
2. It could mis-book a donor sponsorship invoice as a team-plan payment.

These tests pin the processing-side guard (Guard B). The verifier-side guard
(Guard A in ``webhook_verifier``) is exercised by the live cross-delivery
reproduction. See docs/payments/LOCAL_STRIPE_WEBHOOKS.md.
"""
from __future__ import annotations

import pytest

from components.payments.infrastructure.repositories.team_plan_webhook_repository import (
    TeamPlanWebhookRepository,
)


def _repo() -> TeamPlanWebhookRepository:
    # Guard B returns before any dependency is used, so trivial stand-ins are
    # sufficient for these unit tests.
    return TeamPlanWebhookRepository(
        payment_transactions=object(),
        record_successful_payment_use_case=object(),
    )


def test_connect_event_is_ignored_without_processing(monkeypatch):
    """An event carrying ``account`` (a Connect event) is a no-op here."""
    repo = _repo()
    resolved = {"called": False}

    def _spy_resolve(**_kwargs):
        resolved["called"] = True
        return "sk_test_should_not_be_reached"

    # If the guard fails, the handler proceeds to resolve the Stripe key.
    monkeypatch.setattr(TeamPlanWebhookRepository, "_resolve_api_key", staticmethod(_spy_resolve))

    result = repo.handle_verified_webhook(
        event={
            "type": "invoice.payment_succeeded",
            "account": "acct_connected_account",
            "data": {"object": {"id": "in_test"}},
        },
        workspace=None,
        method=None,
        payment_event=None,
        api_key=None,
    )

    assert result is None
    # The guard returns BEFORE any processing — the platform handler never runs.
    assert resolved["called"] is False


def test_platform_event_passes_the_connect_scope_guard(monkeypatch):
    """An event with NO ``account`` (a platform event) is unaffected by the guard."""
    repo = _repo()
    resolved = {"called": False}

    def _spy_resolve(**_kwargs):
        resolved["called"] = True
        return "sk_test_platform"

    monkeypatch.setattr(TeamPlanWebhookRepository, "_resolve_api_key", staticmethod(_spy_resolve))
    # Unhandled type + payment_event=None -> the handler no-ops after the guard.
    monkeypatch.setattr("stripe.api_key", "", raising=False)

    repo.handle_verified_webhook(
        event={"type": "some.unhandled.platform.event", "data": {"object": {}}},
        workspace=None,
        method=None,
        payment_event=None,
        api_key=None,
    )

    # Platform events proceed past the guard into normal processing.
    assert resolved["called"] is True

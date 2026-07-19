"""Integration tests for checkout flows: events, validation scenarios.

Uses the shared ``payment_workspace`` fixture from conftest.py to ensure every
revenue source is tested against the same workspace/method/plan setup.

Note: Campaign and sponsorship integration tests already exist in
components/sponsorship/tests/integration/test_campaign_checkout_api.py
and test_sponsors_checkout_api.py. This file focuses on the new event
checkout and cross-flow validation.
"""

from __future__ import annotations

import pytest
from django.urls import reverse


def _configure_stripe(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_checkout_flows"
    settings.STRIPE_PUBLISHABLE_KEY = "pk_test_checkout_flows"


@pytest.mark.django_db
class TestEventCheckoutValidation:
    """Event checkout input validation works correctly."""

    def test_event_not_found_returns_error(self, api_client, settings):
        _configure_stripe(settings)

        payload = {
            "event_id": "00000000-0000-0000-0000-000000000000",
            "amount": "1000",
            "email": "test@example.com",
        }

        response = api_client.post(reverse("events:event-checkout"), data=payload, format="json")

        assert response.status_code in (400, 404)
        assert "not found" in response.data.get("message", "").lower()

    def test_workspace_mismatch_returns_error(self, api_client, payment_workspace, settings):
        _configure_stripe(settings)
        pw = payment_workspace

        payload = {
            "event_id": str(pw.event.id),
            "workspace_id": "00000000-0000-0000-0000-000000000000",
            "amount": "1000",
            "email": "test@example.com",
        }

        response = api_client.post(reverse("events:event-checkout"), data=payload, format="json")

        assert response.status_code == 400
        assert "workspace" in response.data.get("message", "").lower()

    def test_invalid_amount_returns_error(self, api_client, payment_workspace, settings):
        _configure_stripe(settings)
        pw = payment_workspace

        payload = {
            "event_id": str(pw.event.id),
            "amount": "not-a-number",
            "email": "test@example.com",
        }

        response = api_client.post(reverse("events:event-checkout"), data=payload, format="json")

        assert response.status_code == 400
        assert "numeric" in response.data.get("message", "").lower()


@pytest.mark.django_db
class TestPaymentWorkspaceFixtureIntegrity:
    """Verify the shared payment_workspace fixture creates everything needed."""

    def test_workspace_has_active_method(self, payment_workspace):
        pw = payment_workspace
        assert pw.method.status == "active"
        assert pw.method.is_primary

    def test_all_contexts_have_plans(self, payment_workspace):
        pw = payment_workspace
        for context in ("recipient_sponsorship", "workspace_support", "campaign", "event", "event_ticket", "shop"):
            assert context in pw.plans, f"Missing plan for context: {context}"

    def test_event_linked_to_campaign(self, payment_workspace):
        pw = payment_workspace
        assert pw.event.campaign_id == pw.campaign.id

    def test_recipient_exists(self, payment_workspace):
        pw = payment_workspace
        assert pw.recipient is not None
        assert pw.recipient.workspace_id == pw.workspace.id

    def test_recipient_has_specific_sponsorship_plan(self, payment_workspace):
        pw = payment_workspace
        plan = pw.plans["recipient_sponsorship_specific"]
        assert plan.recipient_id == pw.recipient.id
        assert plan.is_recurring

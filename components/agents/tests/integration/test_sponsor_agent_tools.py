"""SponsorAgent tools — seeded-data integration test.

Verifies the donor-facing read tools return the signed-in sponsor's OWN
data (email-scoped), reusing the same read service that backs the REST
endpoints (so the agent and the UI can't drift). Tools are called directly
with a lightweight stub carrying ``user_id`` + ``workspace_id`` — the
context ``BaseAgent`` injects — which keeps the test fast and LLM-free per
the agents skill (§5.5).
"""
from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    sponsor_agent as sponsor_tools,
)
from infrastructure.persistence.sponsorship.sponsors.models import (
    Sponsor,
    Sponsorship,
)


pytestmark = [pytest.mark.django_db]


class _AgentStub:
    """Minimal stand-in for the agent context the tools read."""

    def __init__(self, user_id, workspace_id):
        self.user_id = str(user_id)
        self.workspace_id = str(workspace_id)


def _make_sponsorship(workspace, recipient, email):
    sponsor = Sponsor.objects.create(name="Test Sponsor", email=email)
    return Sponsorship.objects.create(
        sponsor=sponsor,
        recipient=recipient,
        workspace=workspace,
        context="recipient_sponsorship",
        start_date=datetime.date(2026, 1, 1),
        payment_amount=Decimal("25.00"),
        payment_frequency="monthly",
        payment_status="successful",
        description="Monthly support",
        recurring=True,
        is_active=True,
        currency="USD",
        next_billing_date="2026-07-01",
        stripe_subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
    )


class TestSponsorAgentTools:
    def test_my_sponsorships_returns_own_sponsorship_pii_safe(
        self, workspace_factory, user_factory, recipient_factory
    ):
        user = user_factory(email="sponsor@example.com")
        ws = workspace_factory()
        recipient = recipient_factory(
            workspace=ws, first_name="Amani", last_name="Otieno"
        )
        _make_sponsorship(ws, recipient, "sponsor@example.com")
        # A different sponsor's row must not surface.
        _make_sponsorship(ws, recipient, "someone-else@example.com")

        out = json.loads(
            sponsor_tools.my_sponsorships(_AgentStub(user.id, ws.id), "{}")
        )
        assert out["ok"] is True
        assert out["count"] == 1
        row = out["sponsorships"][0]
        assert row["recipient"] == "Amani O."  # PII-safe, never "Otieno"
        assert row["amount"] == "25.00"
        assert row["status"] == "successful"
        assert "Otieno" not in json.dumps(out)

    def test_my_giving_summary_and_donations(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.donations.models import (
            Donation,
        )

        user = user_factory(email="donor@example.com")
        ws = workspace_factory()
        Donation.objects.create(
            amount=Decimal("50.00"),
            currency="USD",
            email="donor@example.com",
            workspace=ws,
            is_anonymous=False,
            purpose="Gift",
            personalnote="Keep it up",
        )
        agent = _AgentStub(user.id, ws.id)

        summary = json.loads(sponsor_tools.my_giving_summary(agent, "{}"))
        assert summary["ok"] is True
        usd = next(
            e for e in summary["summary_by_currency"] if e["currency"] == "USD"
        )
        assert usd["total_donated"] == "50.00"

        donations = json.loads(sponsor_tools.my_donations(agent, "{}"))
        assert donations["ok"] is True
        assert donations["count"] == 1
        usd_total = next(
            t for t in donations["totals_by_currency"] if t["currency"] == "USD"
        )
        assert usd_total["total_donated"] == "50.00"

    def test_no_email_returns_graceful_error(
        self, workspace_factory, user_factory
    ):
        user = user_factory(email="")
        ws = workspace_factory()
        out = json.loads(
            sponsor_tools.my_sponsorships(_AgentStub(user.id, ws.id), "{}")
        )
        assert out["ok"] is False
        assert "email" in out["error"].lower()

"""DB-backed tests for sponsorship_agent update/cancel tools (PR-C3).

Closes the model-tool symmetry on Recipient, Sponsor, Sponsorship,
and recipient Goals. The audit found sponsorship_agent had
``create_*`` and ``get_*_info`` for everything but no way to update
existing entities or cancel a sponsorship from chat.

These tests exercise the actual ORM (no mocks) to catch any future
schema drift in the sponsorship domain.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from components.agents.infrastructure.adapters.langchain.tools import (
    sponsorship_agent as sponsorship_tools,
)


def _make_agent(workspace_id, user=None):
    agent = MagicMock()
    agent.workspace_id = str(workspace_id)
    agent.user_id = str(user.id) if user else None
    agent.config = {}
    return agent


@pytest.fixture
def sponsorship_setup(workspace_factory, user_factory):
    """Workspace + recipient + sponsor + active sponsorship."""
    from infrastructure.persistence.sponsorship.recipients.models import Recipient
    from infrastructure.persistence.sponsorship.sponsors.models import (
        Sponsor,
        Sponsorship,
    )

    user = user_factory()
    workspace = workspace_factory(owner=user)
    recipient = Recipient.objects.create(
        workspace_id=workspace.id,
        user=user,
        first_name="Original",
        last_name="Recipient",
    )
    sponsor = Sponsor.objects.create(
        name="Donor Smith", email="donor@example.com"
    )
    sponsorship = Sponsorship.objects.create(
        sponsor=sponsor,
        recipient=recipient,
        workspace_id=workspace.id,
        start_date=date.today(),
        payment_amount=Decimal("100.00"),
        payment_frequency="monthly",
        payment_status="successful",
        description="Active sponsorship",
        is_active=True,
        context="recipient_sponsorship",
    )
    return {
        "user": user,
        "workspace": workspace,
        "recipient": recipient,
        "sponsor": sponsor,
        "sponsorship": sponsorship,
        "agent": _make_agent(workspace.id, user),
    }


# ── update_recipient ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateRecipient:
    def test_renames_recipient(self, sponsorship_setup):
        result = sponsorship_tools.update_recipient(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "first_name": "NewFirst",
                "last_name": "NewLast",
            },
        )
        sponsorship_setup["recipient"].refresh_from_db()
        assert sponsorship_setup["recipient"].first_name == "NewFirst"
        assert sponsorship_setup["recipient"].last_name == "NewLast"
        assert "Updated recipient" in result

    def test_updates_age_and_goal(self, sponsorship_setup):
        sponsorship_tools.update_recipient(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "age": 12,
                "goal_amount": "5000.00",
            },
        )
        sponsorship_setup["recipient"].refresh_from_db()
        assert sponsorship_setup["recipient"].age == 12
        assert sponsorship_setup["recipient"].goal_amount == Decimal("5000.00")

    def test_clears_goal(self, sponsorship_setup):
        sponsorship_setup["recipient"].goal_amount = Decimal("999.00")
        sponsorship_setup["recipient"].save(update_fields=["goal_amount"])
        sponsorship_tools.update_recipient(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "goal_amount": None,
            },
        )
        sponsorship_setup["recipient"].refresh_from_db()
        assert sponsorship_setup["recipient"].goal_amount is None

    def test_rejects_invalid_age(self, sponsorship_setup):
        result = sponsorship_tools.update_recipient(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "age": "twelve",
            },
        )
        assert "Invalid age" in result

    def test_rejects_invalid_goal(self, sponsorship_setup):
        result = sponsorship_tools.update_recipient(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "goal_amount": "lots",
            },
        )
        assert "Invalid goal_amount" in result

    def test_rejects_no_fields(self, sponsorship_setup):
        result = sponsorship_tools.update_recipient(
            sponsorship_setup["agent"],
            {"recipient_id": str(sponsorship_setup["recipient"].id)},
        )
        assert "No fields provided" in result

    def test_rejects_cross_workspace(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.recipients.models import Recipient

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        r_in_b = Recipient.objects.create(
            workspace_id=ws_b.id, user=u, first_name="In B", last_name=""
        )
        result = sponsorship_tools.update_recipient(
            _make_agent(ws_a.id, u),
            {"recipient_id": str(r_in_b.id), "first_name": "Hijack"},
        )
        assert "not found" in result
        r_in_b.refresh_from_db()
        assert r_in_b.first_name == "In B"


# ── update_sponsor ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateSponsor:
    def test_updates_name_and_email(self, sponsorship_setup):
        sponsorship_tools.update_sponsor(
            sponsorship_setup["agent"],
            {
                "sponsor_id": str(sponsorship_setup["sponsor"].id),
                "name": "Renamed Sponsor",
                "email": "new@example.com",
            },
        )
        sponsorship_setup["sponsor"].refresh_from_db()
        assert sponsorship_setup["sponsor"].name == "Renamed Sponsor"
        assert sponsorship_setup["sponsor"].email == "new@example.com"

    def test_rejects_empty_name(self, sponsorship_setup):
        result = sponsorship_tools.update_sponsor(
            sponsorship_setup["agent"],
            {"sponsor_id": str(sponsorship_setup["sponsor"].id), "name": " "},
        )
        assert "name cannot be empty" in result

    def test_rejects_invalid_email(self, sponsorship_setup):
        result = sponsorship_tools.update_sponsor(
            sponsorship_setup["agent"],
            {"sponsor_id": str(sponsorship_setup["sponsor"].id), "email": "not-an-email"},
        )
        assert "Invalid email" in result

    def test_rejects_sponsor_outside_workspace(
        self, sponsorship_setup, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.sponsors.models import Sponsor

        # Sponsor with no sponsorships in this workspace.
        unrelated = Sponsor.objects.create(name="Stranger", email="s@example.com")
        result = sponsorship_tools.update_sponsor(
            sponsorship_setup["agent"],
            {"sponsor_id": str(unrelated.id), "name": "Trying"},
        )
        assert "no sponsorships" in result.lower()


# ── update_sponsorship_status ─────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateSponsorshipStatus:
    def test_changes_payment_status(self, sponsorship_setup):
        sponsorship_tools.update_sponsorship_status(
            sponsorship_setup["agent"],
            {
                "sponsorship_id": str(sponsorship_setup["sponsorship"].id),
                "payment_status": "failed",
            },
        )
        sponsorship_setup["sponsorship"].refresh_from_db()
        assert sponsorship_setup["sponsorship"].payment_status == "failed"

    def test_rejects_unknown_status(self, sponsorship_setup):
        result = sponsorship_tools.update_sponsorship_status(
            sponsorship_setup["agent"],
            {
                "sponsorship_id": str(sponsorship_setup["sponsorship"].id),
                "payment_status": "weird",
            },
        )
        assert "Invalid payment_status" in result


# ── cancel_sponsorship ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestCancelSponsorship:
    def test_marks_sponsorship_inactive(self, sponsorship_setup):
        sponsorship_tools.cancel_sponsorship(
            sponsorship_setup["agent"],
            {"sponsorship_id": str(sponsorship_setup["sponsorship"].id)},
        )
        sponsorship_setup["sponsorship"].refresh_from_db()
        assert sponsorship_setup["sponsorship"].is_active is False
        assert sponsorship_setup["sponsorship"].ended_at is not None

    def test_idempotent_on_already_cancelled(self, sponsorship_setup):
        sponsorship_setup["sponsorship"].is_active = False
        sponsorship_setup["sponsorship"].ended_at = timezone.now()
        sponsorship_setup["sponsorship"].save()
        result = sponsorship_tools.cancel_sponsorship(
            sponsorship_setup["agent"],
            {"sponsorship_id": str(sponsorship_setup["sponsorship"].id)},
        )
        assert "already inactive" in result


# ── manage_sponsorship_goal ───────────────────────────────────────────


@pytest.mark.django_db
class TestManageSponsorshipGoal:
    def test_creates_goal(self, sponsorship_setup):
        from infrastructure.persistence.sponsorship.recipients.models import Goal

        sponsorship_tools.manage_sponsorship_goal(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "action": "create",
                "name": "School fees Q3",
                "amount": "1500.00",
                "description": "September quarter",
            },
        )
        goal = Goal.objects.filter(
            recipient=sponsorship_setup["recipient"], name="School fees Q3"
        ).first()
        assert goal is not None
        assert goal.amount == Decimal("1500.00")

    def test_create_rejects_missing_name(self, sponsorship_setup):
        result = sponsorship_tools.manage_sponsorship_goal(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "action": "create",
                "amount": "100.00",
            },
        )
        assert "name is required" in result

    def test_funds_goal(self, sponsorship_setup):
        from infrastructure.persistence.sponsorship.recipients.models import Goal

        goal = Goal.objects.create(
            workspace_id=sponsorship_setup["workspace"].id,
            user=sponsorship_setup["user"],
            recipient=sponsorship_setup["recipient"],
            name="To fund",
            amount=Decimal("200.00"),
            description="x",
        )
        sponsorship_tools.manage_sponsorship_goal(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "action": "fund",
                "goal_id": str(goal.id),
            },
        )
        goal.refresh_from_db()
        assert goal.funded is True
        assert goal.status is True

    def test_deletes_goal(self, sponsorship_setup):
        from infrastructure.persistence.sponsorship.recipients.models import Goal

        goal = Goal.objects.create(
            workspace_id=sponsorship_setup["workspace"].id,
            user=sponsorship_setup["user"],
            recipient=sponsorship_setup["recipient"],
            name="Doomed",
            amount=Decimal("50.00"),
            description="x",
        )
        gid = goal.id
        sponsorship_tools.manage_sponsorship_goal(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "action": "delete",
                "goal_id": str(gid),
            },
        )
        assert not Goal.objects.filter(id=gid).exists()

    def test_rejects_unknown_action(self, sponsorship_setup):
        result = sponsorship_tools.manage_sponsorship_goal(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "action": "summon",
            },
        )
        assert "Invalid action" in result

    def test_rejects_goal_outside_recipient(
        self, sponsorship_setup, user_factory, workspace_factory
    ):
        """A goal attached to OTHER recipient must be invisible."""
        from infrastructure.persistence.sponsorship.recipients.models import (
            Goal,
            Recipient,
        )

        other_recipient = Recipient.objects.create(
            workspace_id=sponsorship_setup["workspace"].id,
            user=sponsorship_setup["user"],
            first_name="Other",
            last_name="Recipient",
        )
        other_goal = Goal.objects.create(
            workspace_id=sponsorship_setup["workspace"].id,
            user=sponsorship_setup["user"],
            recipient=other_recipient,
            name="Other goal",
            amount=Decimal("100.00"),
            description="x",
        )
        result = sponsorship_tools.manage_sponsorship_goal(
            sponsorship_setup["agent"],
            {
                "recipient_id": str(sponsorship_setup["recipient"].id),
                "action": "fund",
                "goal_id": str(other_goal.id),
            },
        )
        assert "not found on this recipient" in result
        other_goal.refresh_from_db()
        assert other_goal.funded is False

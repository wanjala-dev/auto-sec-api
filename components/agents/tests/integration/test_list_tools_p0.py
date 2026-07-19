"""P0 list tools — proven hallucination-prevention shape.

The 2026-05-08 audit identified four missing workspace-scoped list
tools. Without them, "how many tasks?" / "how many campaigns?" /
"who are my recipients?" / "who are our sponsors?" each thrashed the
ReAct loop into a hallucinated answer. These integration tests pin the
fix end-to-end against the real DB.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    donation_agent as donation_tools,
    financial_agent as financial_tools,
    fundraising_agent as fundraising_tools,
    sponsorship_agent as sponsorship_tools,
    task_agent as task_tools,
)


def _make_agent_stub(workspace_id):
    """Minimal agent stub — list tools only read ``workspace_id``."""
    agent = MagicMock()
    agent.workspace_id = workspace_id
    return agent


@pytest.mark.django_db
class TestListWorkspaceTasks:
    def test_returns_zero_for_empty_workspace(
        self, workspace_factory
    ):
        ws = workspace_factory()
        result = task_tools.list_workspace_tasks(_make_agent_stub(ws.id), {})
        assert "No tasks" in result

    def test_lists_workspace_tasks_only(
        self, workspace_factory, user_factory, team_factory
    ):
        from infrastructure.persistence.project.models import Task

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        team_a = team_factory(workspace=ws_a, created_by=u)
        team_b = team_factory(workspace=ws_b, created_by=u)

        Task.objects.create(
            workspace_id=ws_a.id,
            team=team_a,
            title="Alpha task",
            created_by=u,
        )
        Task.objects.create(
            workspace_id=ws_b.id,
            team=team_b,
            title="Bravo task (other workspace)",
            created_by=u,
        )

        result = task_tools.list_workspace_tasks(_make_agent_stub(ws_a.id), {})
        assert "Alpha task" in result
        assert "Bravo task" not in result, (
            "Cross-workspace leak — list_workspace_tasks must scope by "
            "agent.workspace_id."
        )

    def test_status_filter_excludes_archived_by_default(
        self, workspace_factory, user_factory, team_factory
    ):
        from infrastructure.persistence.project.models import Task

        u = user_factory()
        ws = workspace_factory(owner=u)
        team = team_factory(workspace=ws, created_by=u)

        Task.objects.create(
            workspace_id=ws.id, team=team, title="active", created_by=u
        )
        Task.objects.create(
            workspace_id=ws.id,
            team=team,
            title="archived",
            created_by=u,
            status=Task.ARCHIVED,
        )
        result = task_tools.list_workspace_tasks(_make_agent_stub(ws.id), {})
        assert "active" in result
        assert "archived" not in result

    def test_explicit_status_filter_includes_archived(
        self, workspace_factory, user_factory, team_factory
    ):
        from infrastructure.persistence.project.models import Task

        u = user_factory()
        ws = workspace_factory(owner=u)
        team = team_factory(workspace=ws, created_by=u)
        Task.objects.create(
            workspace_id=ws.id,
            team=team,
            title="archived",
            created_by=u,
            status=Task.ARCHIVED,
        )
        result = task_tools.list_workspace_tasks(
            _make_agent_stub(ws.id), {"status": "archived"}
        )
        assert "archived" in result

    def test_handles_missing_workspace_context(self):
        agent = MagicMock()
        agent.workspace_id = None
        result = task_tools.list_workspace_tasks(agent, {})
        assert "No workspace context" in result


@pytest.mark.django_db
class TestListCampaigns:
    def test_lists_workspace_campaigns_only(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.campaign.models import (
            Campaign,
        )

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        Campaign.objects.create(
            name="Alpha campaign",
            description="desc",
            workspace_id=ws_a.id,
            user_id=u.id,
        )
        Campaign.objects.create(
            name="Bravo campaign",
            description="desc",
            workspace_id=ws_b.id,
            user_id=u.id,
        )
        result = fundraising_tools.list_campaigns(
            _make_agent_stub(ws_a.id), {}
        )
        assert "Alpha campaign" in result
        assert "Bravo campaign" not in result

    def test_active_filter(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.campaign.models import (
            Campaign,
        )

        u = user_factory()
        ws = workspace_factory(owner=u)
        Campaign.objects.create(
            name="Live", description="d", workspace_id=ws.id, user_id=u.id, is_active=True
        )
        Campaign.objects.create(
            name="Closed", description="d", workspace_id=ws.id, user_id=u.id, is_active=False
        )
        active = fundraising_tools.list_campaigns(
            _make_agent_stub(ws.id), {"status": "active"}
        )
        assert "Live" in active
        assert "Closed" not in active

    def test_count_campaigns_returns_count(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.campaign.models import (
            Campaign,
        )

        u = user_factory()
        ws = workspace_factory(owner=u)
        Campaign.objects.create(
            name="A", description="d", workspace_id=ws.id, user_id=u.id, is_active=True
        )
        Campaign.objects.create(
            name="B", description="d", workspace_id=ws.id, user_id=u.id, is_active=False
        )
        result = fundraising_tools.count_campaigns(_make_agent_stub(ws.id), {})
        assert "2 campaign" in result.lower()
        assert "1 active" in result.lower()


@pytest.mark.django_db
class TestListRecipients:
    def test_lists_workspace_recipients_only(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.recipients.models import (
            Recipient,
        )

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        Recipient.objects.create(
            workspace_id=ws_a.id, user=u, first_name="Alpha", last_name="Person"
        )
        Recipient.objects.create(
            workspace_id=ws_b.id, user=u, first_name="Bravo", last_name="Person"
        )
        result = sponsorship_tools.list_recipients(
            _make_agent_stub(ws_a.id), {}
        )
        assert "Alpha Person" in result
        assert "Bravo Person" not in result

    def test_excludes_deleted_recipients(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.recipients.models import (
            Recipient,
        )

        u = user_factory()
        ws = workspace_factory(owner=u)
        Recipient.objects.create(
            workspace_id=ws.id, user=u, first_name="Alive", last_name="Person"
        )
        Recipient.objects.create(
            workspace_id=ws.id,
            user=u,
            first_name="Deleted",
            last_name="Person",
            deleted=True,
        )
        result = sponsorship_tools.list_recipients(
            _make_agent_stub(ws.id), {}
        )
        assert "Alive Person" in result
        assert "Deleted Person" not in result


@pytest.mark.django_db
class TestListSponsors:
    def test_lists_sponsors_via_sponsorship(
        self, workspace_factory, user_factory
    ):
        from datetime import date

        from infrastructure.persistence.sponsorship.recipients.models import (
            Recipient,
        )
        from infrastructure.persistence.sponsorship.sponsors.models import (
            Sponsor,
            Sponsorship,
        )

        u = user_factory()
        ws = workspace_factory(owner=u)
        recipient = Recipient.objects.create(
            workspace_id=ws.id, user=u, first_name="R", last_name="P"
        )
        sponsor = Sponsor.objects.create(name="Donor One", email="d1@example.com")
        Sponsorship.objects.create(
            sponsor=sponsor,
            recipient=recipient,
            workspace_id=ws.id,
            start_date=date.today(),
            payment_amount=Decimal("100.00"),
            payment_frequency="monthly",
            payment_status="successful",
            description="desc",
            is_active=True,
            context="recipient_sponsorship",
        )
        result = sponsorship_tools.list_sponsors(_make_agent_stub(ws.id), {})
        assert "Donor One" in result

    def test_returns_helpful_when_empty(
        self, workspace_factory
    ):
        ws = workspace_factory()
        result = sponsorship_tools.list_sponsors(_make_agent_stub(ws.id), {})
        assert "No sponsors" in result


@pytest.mark.django_db
class TestListDonors:
    def test_aggregates_donors_by_identity(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.donations.models import (
            Donation,
        )

        u = user_factory()
        ws = workspace_factory(owner=u)
        # Two donations from the same donor — should appear once in
        # the aggregated list, with donation_count=2.
        Donation.objects.create(
            workspace_id=ws.id, amount=Decimal("100.00"),
            email="donor@example.com", name="Repeat Donor",
        )
        Donation.objects.create(
            workspace_id=ws.id, amount=Decimal("250.00"),
            email="donor@example.com", name="Repeat Donor",
        )
        result = donation_tools.list_donors(_make_agent_stub(ws.id), {})
        assert "Repeat Donor" in result
        assert result.count("Repeat Donor") == 1, (
            "Donors must be aggregated — same (email, name) pair should "
            "appear once with donation_count=2, not twice."
        )
        assert "Donations: 2" in result
        assert "Total given: $350.00" in result

    def test_excludes_anonymous(self, workspace_factory):
        from infrastructure.persistence.sponsorship.donations.models import (
            Donation,
        )

        ws = workspace_factory()
        # Build the rows manually + ``_skip_ingest`` so the post-save
        # transaction sync side-effect doesn't fire (it isn't relevant
        # to the listing logic and pulls in a lot of unrelated state).
        real = Donation(
            workspace_id=ws.id, amount=Decimal("100.00"),
            email="real@example.com", name="Real Donor",
            is_anonymous=False,
        )
        real._skip_ingest = True
        real.save()
        hidden = Donation(
            workspace_id=ws.id, amount=Decimal("50.00"),
            email="hidden@anon.com", name="Hidden Donor",
            is_anonymous=True,
        )
        hidden._skip_ingest = True
        hidden.save()
        # Sanity: confirm the row really did persist with is_anonymous=True.
        # If this fails, the bug is in the model layer, not list_donors.
        assert Donation.objects.filter(
            workspace_id=ws.id, is_anonymous=True
        ).count() == 1, "is_anonymous didn't persist as True"

        result = donation_tools.list_donors(_make_agent_stub(ws.id), {})
        assert "Real Donor" in result
        assert "Hidden Donor" not in result
        # Anonymous count surfaced in the header.
        assert "1 anonymous donation" in result


@pytest.mark.django_db
class TestTopDonors:
    def test_orders_by_total_given(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.sponsorship.donations.models import (
            Donation,
        )

        ws = workspace_factory()
        Donation.objects.create(
            workspace_id=ws.id, amount=Decimal("50.00"),
            email="small@example.com", name="Small Giver",
        )
        Donation.objects.create(
            workspace_id=ws.id, amount=Decimal("1000.00"),
            email="big@example.com", name="Big Giver",
        )
        result = donation_tools.top_donors(
            _make_agent_stub(ws.id), {"limit": 5}
        )
        # Big Giver must appear before Small Giver in the output.
        big_idx = result.find("Big Giver")
        small_idx = result.find("Small Giver")
        assert big_idx >= 0 and small_idx >= 0
        assert big_idx < small_idx, "Top donors must be ordered by total."

    def test_period_filter_restricts_window(
        self, workspace_factory, user_factory
    ):
        from datetime import timedelta
        from django.utils import timezone

        from infrastructure.persistence.sponsorship.donations.models import (
            Donation,
        )

        ws = workspace_factory()
        recent = Donation.objects.create(
            workspace_id=ws.id, amount=Decimal("100.00"),
            email="recent@example.com", name="Recent",
        )
        old = Donation.objects.create(
            workspace_id=ws.id, amount=Decimal("9999.00"),
            email="old@example.com", name="Old Big Donor",
        )
        # Force the "old" row's created_at into the past — bypasses
        # auto_now_add via a direct UPDATE.
        Donation.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=400)
        )
        result = donation_tools.top_donors(
            _make_agent_stub(ws.id), {"period": "last_30_days"}
        )
        assert "Recent" in result
        assert "Old Big Donor" not in result, (
            "Period filter must exclude donations outside the window — "
            "even if they're larger."
        )


@pytest.mark.django_db
class TestListTransactions:
    def test_lists_workspace_transactions_only(
        self, workspace_factory, user_factory
    ):
        from infrastructure.persistence.budget.transactions.models import (
            Transaction,
        )

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        Transaction.objects.create(
            workspace_id=ws_a.id,
            user=u,
            amount=Decimal("100.00"),
            transaction_type="expense",
        )
        Transaction.objects.create(
            workspace_id=ws_b.id,
            user=u,
            amount=Decimal("200.00"),
            transaction_type="income",
        )
        result = financial_tools.list_transactions(
            _make_agent_stub(ws_a.id), {}
        )
        assert "100.00" in result
        assert "200.00" not in result, (
            "Cross-workspace leak — list_transactions must scope by "
            "agent.workspace_id."
        )

    def test_type_filter(self, workspace_factory, user_factory):
        from infrastructure.persistence.budget.transactions.models import (
            Transaction,
        )

        u = user_factory()
        ws = workspace_factory(owner=u)
        Transaction.objects.create(
            workspace_id=ws.id, user=u, amount=Decimal("100.00"),
            transaction_type="expense",
        )
        Transaction.objects.create(
            workspace_id=ws.id, user=u, amount=Decimal("200.00"),
            transaction_type="income",
        )
        only_income = financial_tools.list_transactions(
            _make_agent_stub(ws.id), {"type": "income"}
        )
        assert "200.00" in only_income
        assert "100.00" not in only_income

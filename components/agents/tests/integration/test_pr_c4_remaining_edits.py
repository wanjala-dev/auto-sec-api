"""DB-backed tests for the small remaining P1+P2 edit tools (PR-C4).

Closes the model-tool symmetry on:

- ``donation_agent``: update_recurring_donation, cancel_recurring_donation
- ``financial_agent``: update_transaction, delete_transaction
- ``blog_agent``: delete_news_article, toggle_article_feature

After this PR, every model-with-update-on-the-API has a matching agent
tool. Update/delete asymmetry is closed across the board.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    blog_agent as blog_tools,
    donation_agent as donation_tools,
    financial_agent as financial_tools,
)


def _make_agent(workspace_id, user=None):
    agent = MagicMock()
    agent.workspace_id = str(workspace_id)
    agent.user_id = str(user.id) if user else None
    agent.config = {}
    return agent


# ── donation_agent: recurring update / cancel ──────────────────────────


@pytest.fixture
def recurring_donation(workspace_factory, user_factory):
    """A workspace + a recurring Donation ready to update."""
    from infrastructure.persistence.sponsorship.donations.models import Donation

    user = user_factory()
    workspace = workspace_factory(owner=user)
    donation = Donation(
        workspace_id=workspace.id,
        amount=Decimal("50.00"),
        email="recurring@example.com",
        name="Monthly Donor",
        is_recurring=True,
        next_billing_date="2026-09-01",
    )
    donation._skip_ingest = True
    donation.save()
    return {
        "user": user,
        "workspace": workspace,
        "donation": donation,
        "agent": _make_agent(workspace.id, user),
    }


@pytest.mark.django_db
class TestUpdateRecurringDonation:
    def test_changes_amount(self, recurring_donation):
        donation_tools.update_recurring_donation(
            recurring_donation["agent"],
            {
                "donation_id": str(recurring_donation["donation"].id),
                "amount": "75.00",
            },
        )
        recurring_donation["donation"].refresh_from_db()
        assert recurring_donation["donation"].amount == Decimal("75.00")

    def test_changes_next_billing_date(self, recurring_donation):
        donation_tools.update_recurring_donation(
            recurring_donation["agent"],
            {
                "donation_id": str(recurring_donation["donation"].id),
                "next_billing_date": "2026-12-01",
            },
        )
        recurring_donation["donation"].refresh_from_db()
        assert recurring_donation["donation"].next_billing_date == "2026-12-01"

    def test_clears_next_billing_date(self, recurring_donation):
        donation_tools.update_recurring_donation(
            recurring_donation["agent"],
            {
                "donation_id": str(recurring_donation["donation"].id),
                "next_billing_date": None,
            },
        )
        recurring_donation["donation"].refresh_from_db()
        assert recurring_donation["donation"].next_billing_date == ""

    def test_rejects_non_recurring(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.donations.models import Donation

        u = user_factory()
        ws = workspace_factory(owner=u)
        d = Donation(workspace_id=ws.id, amount=Decimal("10.00"), is_recurring=False)
        d._skip_ingest = True
        d.save()
        result = donation_tools.update_recurring_donation(
            _make_agent(ws.id, u),
            {"donation_id": str(d.id), "amount": "20.00"},
        )
        assert "not marked as recurring" in result

    def test_rejects_invalid_amount(self, recurring_donation):
        result = donation_tools.update_recurring_donation(
            recurring_donation["agent"],
            {
                "donation_id": str(recurring_donation["donation"].id),
                "amount": "free",
            },
        )
        assert "Invalid amount" in result


@pytest.mark.django_db
class TestCancelRecurringDonation:
    def test_clears_recurring_flags(self, recurring_donation):
        donation_tools.cancel_recurring_donation(
            recurring_donation["agent"],
            {"donation_id": str(recurring_donation["donation"].id)},
        )
        recurring_donation["donation"].refresh_from_db()
        assert recurring_donation["donation"].is_recurring is False
        assert recurring_donation["donation"].next_billing_date == ""

    def test_idempotent_on_non_recurring(self, workspace_factory, user_factory):
        from infrastructure.persistence.sponsorship.donations.models import Donation

        u = user_factory()
        ws = workspace_factory(owner=u)
        d = Donation(workspace_id=ws.id, amount=Decimal("10.00"), is_recurring=False)
        d._skip_ingest = True
        d.save()
        result = donation_tools.cancel_recurring_donation(
            _make_agent(ws.id, u), {"donation_id": str(d.id)}
        )
        assert "already not recurring" in result


# ── financial_agent: transaction update / delete ──────────────────────


@pytest.fixture
def transaction_setup(workspace_factory, user_factory):
    from infrastructure.persistence.budget.transactions.models import Transaction

    user = user_factory()
    workspace = workspace_factory(owner=user)
    tx = Transaction.objects.create(
        workspace_id=workspace.id,
        user=user,
        amount=Decimal("250.00"),
        transaction_type="expense",
        date=date(2026, 5, 1),
        notes="Original notes",
    )
    return {
        "user": user,
        "workspace": workspace,
        "tx": tx,
        "agent": _make_agent(workspace.id, user),
    }


@pytest.mark.django_db
class TestUpdateTransaction:
    def test_changes_amount_and_notes(self, transaction_setup):
        financial_tools.update_transaction(
            transaction_setup["agent"],
            {
                "transaction_id": str(transaction_setup["tx"].id),
                "amount": "315.50",
                "notes": "Adjusted",
            },
        )
        transaction_setup["tx"].refresh_from_db()
        assert transaction_setup["tx"].amount == Decimal("315.50")
        assert transaction_setup["tx"].notes == "Adjusted"

    def test_changes_date(self, transaction_setup):
        financial_tools.update_transaction(
            transaction_setup["agent"],
            {
                "transaction_id": str(transaction_setup["tx"].id),
                "date": "2026-06-15",
            },
        )
        transaction_setup["tx"].refresh_from_db()
        actual = transaction_setup["tx"].date
        actual_date = actual.date() if hasattr(actual, "date") else actual
        assert actual_date == date(2026, 6, 15)

    def test_rejects_clearing_date(self, transaction_setup):
        result = financial_tools.update_transaction(
            transaction_setup["agent"],
            {"transaction_id": str(transaction_setup["tx"].id), "date": None},
        )
        assert "cannot be cleared" in result

    def test_rejects_invalid_amount(self, transaction_setup):
        result = financial_tools.update_transaction(
            transaction_setup["agent"],
            {
                "transaction_id": str(transaction_setup["tx"].id),
                "amount": "lots",
            },
        )
        assert "Invalid amount" in result

    def test_rejects_no_fields(self, transaction_setup):
        result = financial_tools.update_transaction(
            transaction_setup["agent"],
            {"transaction_id": str(transaction_setup["tx"].id)},
        )
        assert "No fields provided" in result


@pytest.mark.django_db
class TestDeleteTransaction:
    def test_soft_deletes(self, transaction_setup):
        from infrastructure.persistence.budget.transactions.models import Transaction

        financial_tools.delete_transaction(
            transaction_setup["agent"],
            {"transaction_id": str(transaction_setup["tx"].id)},
        )
        transaction_setup["tx"].refresh_from_db()
        assert transaction_setup["tx"].is_deleted is True
        assert not Transaction.active.filter(
            id=transaction_setup["tx"].id
        ).exists()
        assert Transaction.objects.filter(
            id=transaction_setup["tx"].id
        ).exists()

    def test_rejects_unknown(self, transaction_setup):
        result = financial_tools.delete_transaction(
            transaction_setup["agent"],
            {"transaction_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert "not found" in result


# ── blog_agent: delete + feature toggle ────────────────────────────────


@pytest.fixture
def article_setup(workspace_factory, user_factory):
    import uuid as _uuid

    from infrastructure.persistence.workspaces.news.models import Category, News

    user = user_factory()
    workspace = workspace_factory(owner=user)
    unique = _uuid.uuid4().hex[:8]
    category, _ = Category.objects.get_or_create(name=f"News-{unique}")
    article = News.objects.create(
        workspace=workspace,
        author=user,
        category=category,
        title="Test Article",
        body="Body content",
        excerpt="Excerpt",
        slug=f"test-article-{unique}",
        status=2,  # Draft
    )
    return {
        "user": user,
        "workspace": workspace,
        "category": category,
        "article": article,
        "agent": _make_agent(workspace.id, user),
    }


@pytest.mark.django_db
class TestDeleteNewsArticle:
    def test_deletes_article(self, article_setup):
        from infrastructure.persistence.workspaces.news.models import News

        aid = article_setup["article"].id
        result = blog_tools.delete_news_article(
            article_setup["agent"], {"article_id": str(aid)}
        )
        assert "Deleted article" in result
        assert not News.objects.filter(id=aid).exists()

    def test_rejects_unknown(self, article_setup):
        result = blog_tools.delete_news_article(
            article_setup["agent"],
            {"article_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(self, workspace_factory, user_factory):
        import uuid as _uuid

        from infrastructure.persistence.workspaces.news.models import Category, News

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        unique = _uuid.uuid4().hex[:8]
        category, _ = Category.objects.get_or_create(name=f"News-{unique}")
        article_b = News.objects.create(
            workspace=ws_b, author=u, category=category,
            title="In B", body="x", excerpt="x",
            slug=f"in-b-{unique}", status=2,
        )
        result = blog_tools.delete_news_article(
            _make_agent(ws_a.id, u), {"article_id": str(article_b.id)}
        )
        assert "not found" in result
        assert News.objects.filter(id=article_b.id).exists()


@pytest.mark.django_db
class TestToggleArticleFeature:
    def test_explicit_set_to_featured(self, article_setup):
        article_setup["article"].featured = False
        article_setup["article"].save(update_fields=["featured"])
        blog_tools.toggle_article_feature(
            article_setup["agent"],
            {"article_id": str(article_setup["article"].id), "featured": True},
        )
        article_setup["article"].refresh_from_db()
        assert article_setup["article"].featured is True

    def test_flips_when_no_value_provided(self, article_setup):
        original = article_setup["article"].featured
        blog_tools.toggle_article_feature(
            article_setup["agent"],
            {"article_id": str(article_setup["article"].id)},
        )
        article_setup["article"].refresh_from_db()
        assert article_setup["article"].featured != original

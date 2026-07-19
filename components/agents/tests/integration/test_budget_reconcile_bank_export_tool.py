"""DB-backed integration tests for the ``reconcile_bank_export`` tool."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    budget_agent as budget_tools,
)


pytestmark = pytest.mark.django_db


def _agent(workspace, user):
    return SimpleNamespace(
        workspace_id=str(workspace.id), user_id=str(user.id)
    )


@pytest.fixture
def setup(user_factory, workspace_factory):
    from infrastructure.persistence.budget.models import Budget
    from infrastructure.persistence.budget.transactions.models import Transaction

    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    budget = Budget.objects.create(
        workspace=workspace,
        user=owner,
        name="Test Budget",
        slug=f"test-{workspace.id.hex[:8]}",
    )
    expense = Transaction.objects.create(
        workspace=workspace,
        user=owner,
        budget=budget,
        amount=Decimal("25.00"),
        date=date(2026, 6, 1),
        transaction_type="expense",
        currency="USD",
        notes="Uber ride",
    )
    return {
        "owner": owner,
        "workspace": workspace,
        "expense": expense,
    }


class TestReconcileBankExportTool:
    def test_returns_match_for_matching_row(self, setup):
        agent = _agent(setup["workspace"], setup["owner"])

        result = budget_tools.reconcile_bank_export(
            agent,
            '{"rows": [{"external_id": "BANK_1", "date": "2026-06-01", '
            '"amount": "-25.00", "description": "UBER TRIP"}]}',
        )

        assert "Reconciliation results for 1 row(s)" in result
        assert "UBER TRIP" in result
        assert "score" in result
        assert str(setup["expense"].id) in result

    def test_no_match_when_no_candidates(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = budget_tools.reconcile_bank_export(
            agent,
            '{"rows": [{"external_id": "BANK_1", "date": "2026-06-01", '
            '"amount": "-25.00", "description": "UBER"}]}',
        )

        assert "No candidate matches" in result

    def test_missing_rows_returns_usage(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = budget_tools.reconcile_bank_export(agent, "{}")

        assert "rows is required" in result

    def test_missing_workspace_refused(self, user_factory):
        agent = SimpleNamespace(
            workspace_id=None, user_id=str(user_factory().id)
        )

        result = budget_tools.reconcile_bank_export(
            agent, '{"rows": [{"external_id": "X", "date": "2026-06-01", "amount": "-1"}]}'
        )

        assert "No workspace context" in result

    def test_invalid_row_skipped_with_message(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = budget_tools.reconcile_bank_export(
            agent,
            '{"rows": [{"external_id": "BAD", "date": "not-a-date", '
            '"amount": "-25.00"}]}',
        )

        assert "Could not parse" in result or "Skipped" in result

    def test_min_confidence_filter_applied(self, setup):
        agent = _agent(setup["workspace"], setup["owner"])

        # Same matching row, but with min_confidence very high
        result = budget_tools.reconcile_bank_export(
            agent,
            '{"rows": [{"external_id": "BANK_1", "date": "2026-06-01", '
            '"amount": "-25.00", "description": "UBER TRIP"}], '
            '"min_confidence": 0.99}',
        )

        # Score around 0.85 — should be filtered out
        assert "No candidate matches" in result

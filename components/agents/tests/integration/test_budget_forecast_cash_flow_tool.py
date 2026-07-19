"""DB-backed integration tests for the ``forecast_cash_flow`` tool."""
from __future__ import annotations

from datetime import date, timedelta
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


def _create_tx(workspace, user, budget, when, amount, tx_type):
    from infrastructure.persistence.budget.transactions.models import Transaction

    return Transaction.objects.create(
        workspace=workspace,
        user=user,
        budget=budget,
        amount=amount,
        date=when,
        transaction_type=tx_type,
        currency="USD",
    )


@pytest.fixture
def populated(user_factory, workspace_factory):
    from infrastructure.persistence.budget.models import Budget

    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    budget = Budget.objects.create(
        workspace=workspace,
        user=owner,
        name="Test Budget",
        slug=f"test-{workspace.id.hex[:8]}",
    )
    # 6 weeks of $100 income + $60 expense
    today = date(2026, 6, 15)
    for weeks_back in range(1, 7):
        when = today - timedelta(weeks=weeks_back) + timedelta(days=2)
        _create_tx(workspace, owner, budget, when, Decimal("100"), "income")
        _create_tx(workspace, owner, budget, when, Decimal("60"), "expense")
    return {
        "workspace": workspace,
        "owner": owner,
        "budget": budget,
        "today": today,
    }


class TestForecastCashFlowTool:
    def test_returns_per_week_projections(self, populated):
        ctx = populated
        agent = _agent(ctx["workspace"], ctx["owner"])

        result = budget_tools.forecast_cash_flow(
            agent, f'{{"as_of": "{ctx["today"].isoformat()}", "horizon_weeks": 4}}'
        )

        assert "Cash-flow forecast" in result
        assert "in $100" in result
        assert "out $60" in result
        assert "confidence" in result

    def test_returns_message_when_insufficient_history(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _agent(workspace, owner)

        result = budget_tools.forecast_cash_flow(agent, "{}")

        assert "Not enough transaction history" in result

    def test_missing_workspace_refused(self, user_factory):
        agent = SimpleNamespace(
            workspace_id=None, user_id=str(user_factory().id)
        )

        result = budget_tools.forecast_cash_flow(agent, "{}")

        assert "No workspace context" in result

    def test_invalid_as_of_returns_error(self, populated):
        ctx = populated
        agent = _agent(ctx["workspace"], ctx["owner"])

        result = budget_tools.forecast_cash_flow(
            agent, '{"as_of": "not-a-date"}'
        )

        assert "must be YYYY-MM-DD" in result

    def test_horizon_overrides_default(self, populated):
        ctx = populated
        agent = _agent(ctx["workspace"], ctx["owner"])

        result = budget_tools.forecast_cash_flow(
            agent,
            f'{{"as_of": "{ctx["today"].isoformat()}", "horizon_weeks": 2}}',
        )

        assert "2 weeks" in result

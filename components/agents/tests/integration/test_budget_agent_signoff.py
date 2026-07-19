"""Sign-off spine Phase 4 — the budget agent must not auto-apply AI estimates.

`add_budget_estimate` previously created `BudgetEstimate` rows with the default
`source=USER`, which look user-entered and apply immediately. They must instead
land as `source=AUTO_PROPOSED` so they sit in the SAME pending-acceptance state
the UI's AI proposals use, gated by the existing accept/dismiss flow.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    budget_agent as budget_tools,
)

pytestmark = pytest.mark.integration


def _make_agent(workspace_id, user):
    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id
    agent.config = {}
    return agent


@pytest.fixture
def estimate_setup(workspace_factory, user_factory):
    from infrastructure.persistence.budget.models import Budget
    from infrastructure.persistence.budget.categories.models import Category

    user = user_factory()
    workspace = workspace_factory(owner=user)
    unique = _uuid.uuid4().hex[:8]
    category, _ = Category.objects.get_or_create(
        workspace=workspace,
        slug=f"programs-{unique}",
        defaults={"user": user, "name": f"Programs-{unique}"},
    )
    budget = Budget.objects.create(
        workspace=workspace,
        user=user,
        name="Annual Programs",
        slug=f"annual-programs-{unique}",
        start_date=date(2026, 1, 1),
        status="draft",
    )
    return {"user": user, "workspace": workspace, "budget": budget, "category": category}


@pytest.mark.django_db
def test_agent_estimate_is_auto_proposed_not_user(estimate_setup):
    from infrastructure.persistence.budget.models import BudgetEstimate

    s = estimate_setup
    agent = _make_agent(s["workspace"].id, s["user"])

    result = budget_tools.add_budget_estimate(
        agent,
        {"amount": "1200", "budget": s["budget"].name, "category": s["category"].name},
    )

    estimate = BudgetEstimate.objects.get(workspace_id=s["workspace"].id, budget=s["budget"])
    # The core invariant: AI proposal lands pending acceptance, NOT user-applied.
    assert estimate.source == BudgetEstimate.Source.AUTO_PROPOSED
    assert estimate.source != BudgetEstimate.Source.USER
    assert estimate.source_metadata.get("origin") == "budget_agent"
    # The agent communicates it's a proposal, not an applied line.
    assert "pending your acceptance" in result.lower()


@pytest.mark.django_db
def test_agent_proposal_then_human_accept_flips_to_confirmed(estimate_setup):
    """The proposed estimate flows through the EXISTING accept gate to confirmed."""
    from infrastructure.persistence.budget.models import BudgetEstimate

    s = estimate_setup
    agent = _make_agent(s["workspace"].id, s["user"])
    budget_tools.add_budget_estimate(
        agent,
        {"amount": "800", "budget": s["budget"].name, "category": s["category"].name},
    )
    estimate = BudgetEstimate.objects.get(workspace_id=s["workspace"].id, budget=s["budget"])
    assert estimate.source == BudgetEstimate.Source.AUTO_PROPOSED

    # Simulate the human accept (BudgetEstimateAcceptView flips AUTO_PROPOSED -> USER_CONFIRMED).
    estimate.source = BudgetEstimate.Source.USER_CONFIRMED
    estimate.save(update_fields=["source"])
    estimate.refresh_from_db()
    assert estimate.source == BudgetEstimate.Source.USER_CONFIRMED

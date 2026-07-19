"""DB-backed tests for budget_agent update/delete tools (PR-C2).

Adds the canonical update/delete symmetry on Budget and BudgetEstimate.
The audit found budget_agent had ``create_budget`` + ``add_budget_estimate``
but no way to update or remove either entity from chat. These tools
close that gap; tests confirm workspace scoping + soft-delete semantics.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    budget_agent as budget_tools,
)


def _make_agent(workspace_id, user=None):
    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id if user else None
    agent.config = {}
    return agent


@pytest.fixture
def budget_setup(workspace_factory, user_factory):
    """A workspace + budget with one estimate, ready to edit.

    Categories are auto-seeded per workspace, so we ``get_or_create``
    instead of ``create`` to avoid slug uniqueness collisions when the
    test workspace's bootstrap installs a default "travel" category.
    """
    import uuid as _uuid

    from infrastructure.persistence.budget.models import Budget, BudgetEstimate
    from infrastructure.persistence.budget.categories.models import Category

    user = user_factory()
    workspace = workspace_factory(owner=user)
    unique = _uuid.uuid4().hex[:8]
    category, _ = Category.objects.get_or_create(
        workspace=workspace,
        slug=f"travel-{unique}",
        defaults={"user": user, "name": f"Travel-{unique}"},
    )
    budget = Budget.objects.create(
        workspace=workspace,
        user=user,
        name="Q2 Programs",
        slug=f"q2-programs-{unique}",
        start_date=date(2026, 4, 1),
        status="draft",
    )
    estimate = BudgetEstimate.objects.create(
        workspace=workspace,
        user=user,
        budget=budget,
        category=category,
        label="Quarterly travel",
        amount=Decimal("5000.00"),
        description="Original",
    )
    return {
        "user": user,
        "workspace": workspace,
        "budget": budget,
        "estimate": estimate,
        "category": category,
        "agent": _make_agent(workspace.id, user),
    }


# ── update_budget ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateBudget:
    def test_renames_budget(self, budget_setup):
        result = budget_tools.update_budget(
            budget_setup["agent"],
            {"budget_id": str(budget_setup["budget"].id), "name": "Renamed"},
        )
        budget_setup["budget"].refresh_from_db()
        assert budget_setup["budget"].name == "Renamed"
        assert "Renamed" in result

    def test_updates_start_date(self, budget_setup):
        budget_tools.update_budget(
            budget_setup["agent"],
            {
                "budget_id": str(budget_setup["budget"].id),
                "start_date": "2026-07-01",
            },
        )
        budget_setup["budget"].refresh_from_db()
        # Budget.start_date is a DateTimeField, not DateField; compare via .date().
        actual = budget_setup["budget"].start_date
        actual_date = actual.date() if hasattr(actual, "date") else actual
        assert actual_date == date(2026, 7, 1)

    def test_rejects_clearing_start_date(self, budget_setup):
        # start_date is required on Budget — null clears must fail.
        result = budget_tools.update_budget(
            budget_setup["agent"],
            {
                "budget_id": str(budget_setup["budget"].id),
                "start_date": None,
            },
        )
        assert "cannot be cleared" in result

    def test_rejects_empty_name(self, budget_setup):
        result = budget_tools.update_budget(
            budget_setup["agent"],
            {"budget_id": str(budget_setup["budget"].id), "name": "  "},
        )
        assert "name cannot be empty" in result

    def test_rejects_no_fields(self, budget_setup):
        result = budget_tools.update_budget(
            budget_setup["agent"], {"budget_id": str(budget_setup["budget"].id)}
        )
        assert "No fields provided" in result

    def test_rejects_unknown_budget(self, budget_setup):
        result = budget_tools.update_budget(
            budget_setup["agent"],
            {"budget_id": "00000000-0000-0000-0000-000000000000", "name": "x"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(self, workspace_factory, user_factory):
        import uuid as _uuid

        from infrastructure.persistence.budget.models import Budget

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        budget_in_b = Budget.objects.create(
            workspace=ws_b,
            user=u,
            name="Other workspace",
            slug=f"other-{_uuid.uuid4().hex[:8]}",
            start_date=date(2026, 1, 1),
            status="draft",
        )
        result = budget_tools.update_budget(
            _make_agent(ws_a.id, u),
            {"budget_id": str(budget_in_b.id), "name": "Hijacked"},
        )
        assert "not found" in result
        budget_in_b.refresh_from_db()
        assert budget_in_b.name == "Other workspace"


# ── update_estimate ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateEstimate:
    def test_changes_amount_and_label(self, budget_setup):
        result = budget_tools.update_estimate(
            budget_setup["agent"],
            {
                "estimate_id": str(budget_setup["estimate"].id),
                "label": "Renamed estimate",
                "amount": "7500.50",
            },
        )
        budget_setup["estimate"].refresh_from_db()
        assert budget_setup["estimate"].label == "Renamed estimate"
        assert budget_setup["estimate"].amount == Decimal("7500.50")
        assert "Renamed estimate" in result

    def test_clears_category(self, budget_setup):
        budget_tools.update_estimate(
            budget_setup["agent"],
            {
                "estimate_id": str(budget_setup["estimate"].id),
                "category_id": None,
            },
        )
        budget_setup["estimate"].refresh_from_db()
        assert budget_setup["estimate"].category is None

    def test_assigns_new_category(self, budget_setup, workspace_factory):
        import uuid as _uuid

        from infrastructure.persistence.budget.categories.models import Category

        new_category = Category.objects.create(
            workspace=budget_setup["workspace"],
            user=budget_setup["user"],
            name="Supplies",
            slug=f"supplies-{_uuid.uuid4().hex[:8]}",
        )
        budget_tools.update_estimate(
            budget_setup["agent"],
            {
                "estimate_id": str(budget_setup["estimate"].id),
                "category_id": str(new_category.id),
            },
        )
        budget_setup["estimate"].refresh_from_db()
        assert budget_setup["estimate"].category_id == new_category.id

    def test_rejects_cross_workspace_category(
        self, budget_setup, workspace_factory, user_factory
    ):
        import uuid as _uuid

        from infrastructure.persistence.budget.categories.models import Category

        # Category in DIFFERENT workspace.
        other_user = user_factory()
        other_ws = workspace_factory(owner=other_user)
        other_category = Category.objects.create(
            workspace=other_ws,
            user=other_user,
            name="External",
            slug=f"external-{_uuid.uuid4().hex[:8]}",
        )
        result = budget_tools.update_estimate(
            budget_setup["agent"],
            {
                "estimate_id": str(budget_setup["estimate"].id),
                "category_id": str(other_category.id),
            },
        )
        assert "not found" in result.lower()
        budget_setup["estimate"].refresh_from_db()
        # Original category preserved.
        assert budget_setup["estimate"].category_id == budget_setup["category"].id

    def test_rejects_invalid_amount(self, budget_setup):
        result = budget_tools.update_estimate(
            budget_setup["agent"],
            {
                "estimate_id": str(budget_setup["estimate"].id),
                "amount": "free",
            },
        )
        assert "Invalid amount" in result

    def test_rejects_empty_label(self, budget_setup):
        result = budget_tools.update_estimate(
            budget_setup["agent"],
            {
                "estimate_id": str(budget_setup["estimate"].id),
                "label": "  ",
            },
        )
        assert "label cannot be empty" in result

    def test_rejects_unknown_estimate(self, budget_setup):
        result = budget_tools.update_estimate(
            budget_setup["agent"],
            {"estimate_id": "00000000-0000-0000-0000-000000000000", "label": "x"},
        )
        assert "not found" in result


# ── delete_estimate ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteEstimate:
    def test_soft_deletes_estimate(self, budget_setup):
        from infrastructure.persistence.budget.models import BudgetEstimate

        result = budget_tools.delete_estimate(
            budget_setup["agent"],
            {"estimate_id": str(budget_setup["estimate"].id)},
        )
        budget_setup["estimate"].refresh_from_db()
        assert budget_setup["estimate"].is_deleted is True
        # active manager must hide it now.
        assert not BudgetEstimate.active.filter(
            id=budget_setup["estimate"].id
        ).exists()
        # Hard objects manager still finds it.
        assert BudgetEstimate.objects.filter(
            id=budget_setup["estimate"].id
        ).exists()
        assert "Quarterly travel" in result

    def test_rejects_unknown_estimate(self, budget_setup):
        result = budget_tools.delete_estimate(
            budget_setup["agent"],
            {"estimate_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(self, workspace_factory, user_factory):
        import uuid as _uuid

        from infrastructure.persistence.budget.models import (
            Budget,
            BudgetEstimate,
        )
        from infrastructure.persistence.budget.categories.models import Category

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        unique = _uuid.uuid4().hex[:8]
        category_b = Category.objects.create(
            workspace=ws_b, user=u, name="B", slug=f"b-{unique}"
        )
        budget_b = Budget.objects.create(
            workspace=ws_b, user=u, name="In B", slug=f"in-b-{unique}",
            start_date=date(2026, 1, 1), status="draft",
        )
        estimate_b = BudgetEstimate.objects.create(
            workspace=ws_b, user=u, budget=budget_b, category=category_b,
            label="In B estimate", amount=Decimal("100.00"),
        )
        result = budget_tools.delete_estimate(
            _make_agent(ws_a.id, u), {"estimate_id": str(estimate_b.id)}
        )
        assert "not found" in result
        estimate_b.refresh_from_db()
        assert estimate_b.is_deleted is False

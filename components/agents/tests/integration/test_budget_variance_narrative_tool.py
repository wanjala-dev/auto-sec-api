"""DB-backed integration tests for ``draft_variance_narrative`` tool.

Exercises the full path: ``budget_agent`` tool → use case → port. The
LLM-backed port is swapped for the in-memory fake at the provider level
so the test stays deterministic without hitting OpenAI.

The integration boundary here is the workspace + Category + Transaction
ORM: the tool fetches the workspace's matching category and top
contributing transactions for the period, the use case builds the
context, the fake port returns a scripted narrative, and the tool
formats the response. That round-trip is what we want to lock in.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    budget_agent as budget_tools,
)
from components.budgeting.application.use_cases.draft_variance_narrative_use_case import (
    DraftVarianceNarrativeUseCase,
)
from components.budgeting.domain.value_objects.variance_narrative import (
    VarianceNarrative,
)
from components.budgeting.tests.fakes.in_memory_variance_narrator import (
    InMemoryVarianceNarrator,
)


@pytest.fixture
def patched_use_case(monkeypatch):
    """Swap ``default_use_case`` to return one wired to an in-memory fake."""
    fake = InMemoryVarianceNarrator()
    use_case = DraftVarianceNarrativeUseCase(narrative_port=fake)

    monkeypatch.setattr(
        "components.budgeting.application.providers."
        "variance_narrative_provider.default_use_case",
        lambda: use_case,
    )
    return fake


def _make_workspace_with_marketing(user_factory, workspace_factory):
    """Workspace + Marketing category + a couple of expense rows.

    ``workspace_factory`` already seeds a "Marketing" category (along
    with ~37 other standard ones) so we look it up here rather than
    creating a second row with the same name — the tool's
    ``name__iexact`` lookup would otherwise pick whichever Marketing
    Django returns first, leaving the test asserting against a
    category whose transactions we never created.
    """
    from infrastructure.persistence.budget.categories.models import Category
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
    marketing = (
        Category.active.current_workspace(workspace=workspace.id)
        .filter(name__iexact="Marketing")
        .first()
    )
    if marketing is None:
        marketing = Category.objects.create(
            workspace=workspace,
            user=owner,
            name="Marketing",
            slug=f"marketing-{uuid4().hex[:8]}",
        )
    Transaction.objects.create(
        workspace=workspace, user=owner, budget=budget, category=marketing,
        amount=Decimal("500"), date=date(2026, 2, 15),
        transaction_type="expense", currency="USD",
        notes="Adwords spend Feb 15",
    )
    Transaction.objects.create(
        workspace=workspace, user=owner, budget=budget, category=marketing,
        amount=Decimal("300"), date=date(2026, 2, 22),
        transaction_type="expense", currency="USD",
        notes="Adwords spend Feb 22",
    )
    Transaction.objects.create(
        workspace=workspace, user=owner, budget=budget, category=marketing,
        amount=Decimal("200"), date=date(2026, 3, 1),
        transaction_type="expense", currency="USD",
        notes="Newsletter design",
    )
    return SimpleNamespace(
        workspace=workspace, owner=owner, budget=budget, category=marketing
    )


@pytest.fixture
def populated(user_factory, workspace_factory):
    return _make_workspace_with_marketing(user_factory, workspace_factory)


def _agent(workspace, user):
    return SimpleNamespace(
        workspace_id=str(workspace.id), user_id=str(user.id)
    )


@pytest.mark.django_db
class TestDraftVarianceNarrativeTool:
    def test_returns_narrative_for_known_category(
        self, patched_use_case, populated
    ):
        patched_use_case.script(
            category_name="Marketing",
            transaction_type="expense",
            narrative=VarianceNarrative(
                narrative=(
                    "Marketing spend trended high in late February after the "
                    "Adwords campaign expansion. The top two charges "
                    "($500, $300) both relate to that campaign."
                ),
                suggested_next_action=(
                    "Extend the budget by ~$500 if the campaign is working, "
                    "or pause the high-CPC keywords."
                ),
                confidence=0.85,
            ),
        )
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        assert "Variance narrative for 'Marketing'" in result
        assert "Marketing spend trended high" in result
        assert "Suggested next action" in result
        assert "Extend the budget" in result
        assert "85%" in result
        # The tool computed actual from real transactions:
        # 500 + 300 + 200 = 1000.
        assert "actual USD 1000" in result
        assert "variance +USD 500" in result

    def test_uses_caller_supplied_actual_when_provided(
        self, patched_use_case, populated
    ):
        patched_use_case.script(
            category_name="Marketing",
            transaction_type="expense",
            narrative=VarianceNarrative(
                narrative="ok",
                suggested_next_action="",
                confidence=0.6,
            ),
        )
        agent = _agent(populated.workspace, populated.owner)

        # Caller passes its own actual — the tool should NOT recompute.
        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "1000", "actual": "1500"}',
        )

        assert "planned USD 1000" in result
        assert "actual USD 1500" in result
        assert "variance +USD 500" in result

    def test_includes_top_transactions_in_output(
        self, patched_use_case, populated
    ):
        patched_use_case.script(
            category_name="Marketing",
            transaction_type="expense",
            narrative=VarianceNarrative(
                narrative="ok", suggested_next_action="", confidence=0.6
            ),
        )
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        # Top transactions are rendered, largest amount first.
        assert "Adwords spend Feb 15" in result
        # Ordering: 500 should appear before 300 should appear before 200.
        idx_500 = result.find("USD 500")
        idx_300 = result.find("USD 300")
        idx_200 = result.find("USD 200")
        assert idx_500 < idx_300 < idx_200

    def test_top_n_clamped_to_available_transactions(
        self, patched_use_case, populated
    ):
        patched_use_case.script(
            category_name="Marketing",
            transaction_type="expense",
            narrative=VarianceNarrative(
                narrative="ok", suggested_next_action="", confidence=0.6
            ),
        )
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500", "top_n": 2}',
        )

        # Only 2 transactions shown (top_n).
        assert "Adwords spend Feb 15" in result  # 500
        assert "Adwords spend Feb 22" in result  # 300
        assert "Newsletter design" not in result  # 200 — clipped

    def test_unknown_category_returns_helpful_message(
        self, patched_use_case, populated
    ):
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Unicorn Stipends", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        assert "No category named 'Unicorn Stipends'" in result
        assert len(patched_use_case.calls) == 0, (
            "Port should not be called when the category doesn't exist"
        )

    def test_category_match_is_case_insensitive(
        self, patched_use_case, populated
    ):
        patched_use_case.script(
            category_name="Marketing",
            transaction_type="expense",
            narrative=VarianceNarrative(
                narrative="ok", suggested_next_action="", confidence=0.6
            ),
        )
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "MARKETING", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        # Tool resolved the category despite the casing mismatch.
        assert "Variance narrative for 'Marketing'" in result

    def test_missing_workspace_refused(self, user_factory, patched_use_case):
        agent = SimpleNamespace(
            workspace_id=None, user_id=str(user_factory().id)
        )

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        assert "No workspace context" in result

    def test_missing_category_name_returns_usage_hint(
        self, patched_use_case, populated
    ):
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        assert "category_name is required" in result

    def test_missing_period_returns_usage_hint(
        self, patched_use_case, populated
    ):
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", "planned": "500"}',
        )

        assert "period_start and period_end" in result

    def test_invalid_date_returns_error(self, patched_use_case, populated):
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "yesterday", '
            '"period_end": "today", '
            '"planned": "500"}',
        )

        assert "Invalid date" in result

    def test_end_before_start_returns_error(self, patched_use_case, populated):
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-03-31", '
            '"period_end": "2026-02-01", '
            '"planned": "500"}',
        )

        assert "period_end" in result and "must be on or after" in result

    def test_missing_planned_returns_usage_hint(
        self, patched_use_case, populated
    ):
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31"}',
        )

        assert "planned is required" in result

    def test_port_returns_sentinel_renders_no_narrative_message(
        self, patched_use_case, populated
    ):
        # No script() call → fake returns the empty sentinel → use case
        # translates to None → tool renders the fallback message.
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500"}',
        )

        assert "No confident narrative available" in result

    def test_min_confidence_floor_applied(
        self, patched_use_case, populated
    ):
        patched_use_case.script(
            category_name="Marketing",
            transaction_type="expense",
            narrative=VarianceNarrative(
                narrative="weak guess",
                suggested_next_action="",
                confidence=0.3,
            ),
        )
        agent = _agent(populated.workspace, populated.owner)

        result = budget_tools.draft_variance_narrative(
            agent,
            '{"category_name": "Marketing", '
            '"period_start": "2026-02-01", '
            '"period_end": "2026-03-31", '
            '"planned": "500", "min_confidence": 0.7}',
        )

        assert "No confident narrative available" in result

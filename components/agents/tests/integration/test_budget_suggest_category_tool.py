"""DB-backed integration tests for ``suggest_transaction_category`` tool.

Exercises the full path: ``budget_agent`` tool → use case → port. The
LLM-backed port is swapped for the in-memory fake at the provider level
so the test stays deterministic without hitting OpenAI.

The integration boundary here is the workspace + Category ORM: the tool
fetches the workspace's existing categories from the DB, the use case
matches LLM names back to UUIDs, and the tool formats the response.
That round-trip is what we want to lock in.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    budget_agent as budget_tools,
)
from components.budgeting.application.use_cases.suggest_transaction_category_use_case import (
    SuggestTransactionCategoryUseCase,
)
from components.budgeting.domain.value_objects.category_suggestion import (
    CategorySuggestion,
)
from components.budgeting.tests.fakes.in_memory_category_suggester import (
    InMemoryCategorySuggester,
)


@pytest.fixture
def patched_use_case(monkeypatch):
    """Swap ``default_use_case`` to return one wired to an in-memory fake.

    Yields the fake so the test can script its responses; the patch is
    scoped to one test so other suites continue to see the LLM-backed
    default (which they don't call anyway).
    """
    fake = InMemoryCategorySuggester()
    use_case = SuggestTransactionCategoryUseCase(category_suggester=fake)

    monkeypatch.setattr(
        "components.budgeting.application.providers."
        "category_suggestion_provider.default_use_case",
        lambda: use_case,
    )
    # The tool imports ``default_use_case`` inside the function body so
    # patching the provider module alone is sufficient.
    return fake


@pytest.fixture
def workspace_with_categories(user_factory, workspace_factory):
    """A workspace plus a known set of categories."""
    from infrastructure.persistence.budget.categories.models import Category

    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    transport_slug = f"transport-{uuid4().hex[:8]}"
    food_slug = f"food-{uuid4().hex[:8]}"

    transport, _ = Category.objects.get_or_create(
        workspace=workspace,
        slug=transport_slug,
        defaults={"user": owner, "name": "Transport"},
    )
    food, _ = Category.objects.get_or_create(
        workspace=workspace,
        slug=food_slug,
        defaults={"user": owner, "name": "Food"},
    )

    return SimpleNamespace(
        workspace=workspace,
        owner=owner,
        transport=transport,
        food=food,
    )


@pytest.mark.django_db
class TestSuggestTransactionCategoryTool:
    def test_returns_matched_existing_category(
        self, patched_use_case, workspace_with_categories
    ):
        patched_use_case.script(
            when_description_contains="uber",
            suggestions=[
                CategorySuggestion(
                    category_id=None,
                    category_name="Transport",
                    confidence=0.95,
                    rationale="UBER is a ride-share service",
                )
            ],
        )
        agent = SimpleNamespace(
            workspace_id=str(workspace_with_categories.workspace.id),
            user_id=str(workspace_with_categories.owner.id),
        )

        result = budget_tools.suggest_transaction_category(
            agent, '{"description": "UBER TRIP 04/15"}'
        )

        assert "Category suggestions for 'UBER TRIP 04/15'" in result
        assert "Transport" in result
        assert "existing" in result
        assert "95%" in result

    def test_returns_new_category_when_no_match(
        self, patched_use_case, workspace_with_categories
    ):
        patched_use_case.script(
            when_description_contains="zapier",
            suggestions=[
                CategorySuggestion(
                    category_id=None,
                    category_name="SaaS Subscriptions",
                    confidence=0.8,
                    rationale="Recurring automation tool",
                )
            ],
        )
        agent = SimpleNamespace(
            workspace_id=str(workspace_with_categories.workspace.id),
            user_id=str(workspace_with_categories.owner.id),
        )

        result = budget_tools.suggest_transaction_category(
            agent, '{"description": "Zapier monthly"}'
        )

        assert "SaaS Subscriptions" in result
        assert "new" in result

    def test_returns_explanatory_message_when_port_returns_nothing(
        self, patched_use_case, workspace_with_categories
    ):
        # Scripted to NOT match any description
        agent = SimpleNamespace(
            workspace_id=str(workspace_with_categories.workspace.id),
            user_id=str(workspace_with_categories.owner.id),
        )

        result = budget_tools.suggest_transaction_category(
            agent, '{"description": "totally unknown blob"}'
        )

        assert "No confident category suggestion" in result

    def test_missing_description_returns_usage_hint(
        self, patched_use_case, workspace_with_categories
    ):
        agent = SimpleNamespace(
            workspace_id=str(workspace_with_categories.workspace.id),
            user_id=str(workspace_with_categories.owner.id),
        )

        result = budget_tools.suggest_transaction_category(agent, "{}")

        assert "description is required" in result

    def test_missing_workspace_context_returns_refusal(self, patched_use_case):
        agent = SimpleNamespace(workspace_id=None, user_id="some-id")

        result = budget_tools.suggest_transaction_category(
            agent, '{"description": "anything"}'
        )

        assert "No workspace context available" in result

    def test_passes_amount_and_type_to_port(
        self, patched_use_case, workspace_with_categories
    ):
        patched_use_case.script(
            when_description_contains="starbucks",
            suggestions=[
                CategorySuggestion(
                    category_id=None,
                    category_name="Food",
                    confidence=0.85,
                    rationale="Coffee shop",
                )
            ],
        )
        agent = SimpleNamespace(
            workspace_id=str(workspace_with_categories.workspace.id),
            user_id=str(workspace_with_categories.owner.id),
        )

        budget_tools.suggest_transaction_category(
            agent,
            '{"description": "STARBUCKS", "amount": "$5.50", "type": "expense"}',
        )

        assert len(patched_use_case.calls) == 1
        call = patched_use_case.calls[0]
        assert call["amount"] == "$5.50"
        assert call["transaction_type"] == "expense"
        assert "Transport" in call["existing_categories"]
        assert "Food" in call["existing_categories"]

    def test_min_confidence_floor_applied(
        self, patched_use_case, workspace_with_categories
    ):
        patched_use_case.script(
            when_description_contains="ambiguous",
            suggestions=[
                CategorySuggestion(
                    category_id=None,
                    category_name="Transport",
                    confidence=0.4,
                    rationale="weak signal",
                ),
            ],
        )
        agent = SimpleNamespace(
            workspace_id=str(workspace_with_categories.workspace.id),
            user_id=str(workspace_with_categories.owner.id),
        )

        result = budget_tools.suggest_transaction_category(
            agent,
            '{"description": "Ambiguous", "min_confidence": 0.7}',
        )

        assert "No confident category suggestion" in result, (
            "Low-confidence suggestion should be filtered out by min_confidence"
        )

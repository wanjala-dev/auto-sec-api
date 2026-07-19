"""Integration test: ``TransactionCreated`` → "Categorize" Task on
the agent team Kanban (or no-op when the transaction already has a
category).

Action List item P1 #20 (BudgetSpecialistAgent slot). Fifth and final
specialist through the Phase 3 ``SubscriptionRegistry``. Post-Phase-5
(``AIAction`` retired): the handler writes a Kanban Task carrying
narrative on ``Task.description`` and detector context on
``Task.metadata``.

Scope-check tests baked in:

* Categorised → no card. The whole specialist is about *missing*
  categories; this is the path that catches "operator silently created
  a draft tx" entries before they drift.
* Replay-on-Celery-retry is idempotent.
* Notes truncation lands in the Task title; full notes land in the
  Task description.
* Currency casing is normalised (``usd`` → ``USD``).
* Missing workspace logs + returns; never raises.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from components.agents.application.handlers.transaction_specialist_handler import (
    ACTION_TYPE,
    AGENT_TYPE,
    DETECTOR_KEY,
    handle_transaction_created,
)
from components.budgeting.domain.events.transaction_created_event import (
    TransactionCreated,
)


_NEXT_ID = iter(range(1_000_000, 9_999_999))


def _build_event(
    *,
    workspace_id: UUID,
    transaction_id: int | None = None,
    category_id: int | None = None,
    user_id: UUID | None = None,
    budget_id: int | None = None,
    recipient_id: UUID | None = None,
    transaction_type: str = "expense",
    amount: Decimal = Decimal("42.50"),
    currency: str = "USD",
    notes: str = "Office supplies, June",
    occurred_on: date | None = date(2026, 6, 7),
) -> TransactionCreated:
    return TransactionCreated(
        # transaction_id is an int auto-key in the real ORM; honour the
        # event's type even in tests so the Celery deserialiser
        # round-trip stays consistent.
        transaction_id=(
            transaction_id if transaction_id is not None else next(_NEXT_ID)
        ),
        workspace_id=workspace_id,
        user_id=user_id,
        budget_id=budget_id,
        category_id=category_id,
        recipient_id=recipient_id,
        transaction_type=transaction_type,
        amount=amount,
        currency=currency,
        notes=notes,
        occurred_on=occurred_on,
        created_at=datetime(2026, 6, 7, 14, 30, tzinfo=timezone.utc),
    )


@pytest.mark.django_db
class TestTransactionSpecialistHandler:
    def test_creates_categorize_task_for_uncategorised_transaction(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_transaction_created(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            )
        )
        assert len(tasks) == 1
        task = tasks[0]
        assert task.metadata["action_type"] == ACTION_TYPE
        assert task.metadata["agent_type"] == AGENT_TYPE
        assert task.metadata["detector"] == DETECTOR_KEY
        assert task.metadata["context"]["detector_key"] == DETECTOR_KEY
        assert task.metadata["context"]["transaction_id"] == str(
            event.transaction_id
        )

        assert "Categorize:" in task.title
        # Short notes land in the title verbatim.
        assert "Office supplies, June" in task.title
        # Amount label appears as "USD 42.50" in the title.
        assert "USD 42.50" in task.title

    def test_categorised_transaction_does_not_create_a_card(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id, category_id=42
        )

        handle_transaction_created(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 0
        )

    def test_replayed_event_is_idempotent_on_transaction_id(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_transaction_created(event)
        handle_transaction_created(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 1
        )

    def test_two_transactions_each_get_their_own_task(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        handle_transaction_created(_build_event(workspace_id=workspace.id))
        handle_transaction_created(_build_event(workspace_id=workspace.id))

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 2
        )

    def test_empty_notes_falls_back_to_amount_label(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id, notes="")

        handle_transaction_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task is not None
        # No notes → title uses amount + transaction_type, e.g. "USD 42.50 expense".
        assert "USD 42.50 expense" in task.title
        # And the leading "Categorize:" prefix is still there.
        assert task.title.startswith("Categorize:")

    def test_lowercase_currency_is_normalised_in_context(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id, currency="usd"
        )

        handle_transaction_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task.metadata["context"]["currency"] == "USD"

    def test_long_notes_are_truncated_in_title_full_in_description(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        long_notes = "x" * 200
        event = _build_event(
            workspace_id=workspace.id, notes=long_notes
        )

        handle_transaction_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        # Title was truncated with an ellipsis.
        assert "…" in task.title
        assert len(task.title) < 200
        # Description carries the full operator notes.
        assert long_notes in task.description

    def test_impact_score_is_mid_board(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        handle_transaction_created(_build_event(workspace_id=workspace.id))

        task = Task.objects.filter(
            source_type=f"ai.{ACTION_TYPE}"
        ).first()
        # Categorisation nudges are informational; they sit below the
        # variance + anomaly findings on the Suggested column.
        assert task.metadata["impact_score"] == 20

    def test_missing_workspace_skips_silently(self):
        from infrastructure.persistence.project.models import Task

        event = _build_event(workspace_id=uuid4())

        handle_transaction_created(event)

        assert Task.objects.filter(source_type=f"ai.{ACTION_TYPE}").count() == 0

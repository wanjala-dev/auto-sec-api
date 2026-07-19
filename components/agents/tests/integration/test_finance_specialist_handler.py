"""Integration test: ``FinancialReportGenerated`` → review Task on the
agent team Kanban.

Action List item P1 #22 — proof-of-pattern for Phase 3
(``SubscriptionRegistry`` + ``@subscribes_to``). This handler ships
via the registry — it shows up in ``EXPECTED_SUBSCRIPTIONS`` (locked
in by ``test_subscription_registry_discovery``) and no edit to
``infrastructure/persistence/ai/apps.py`` was needed.

Same contract as the existing specialists post-Phase-5
(Agents-as-Teammates migration retired ``AIAction``):

* Per event, create a Task in "Suggested" carrying narrative on
  ``Task.description`` and detector context on ``Task.metadata``.
* Idempotency on ``(workspace, source_type,
  metadata.idempotency_key)`` where the key is
  ``report_id:<report_id>``.
* Failure isolation: errors log; nothing re-raises.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest

from components.agents.application.handlers.finance_specialist_handler import (
    ACTION_TYPE,
    AGENT_TYPE,
    DETECTOR_KEY,
    handle_financial_report_generated,
)
from components.reports.domain.events import FinancialReportGenerated


def _build_event(
    *,
    workspace_id: UUID,
    report_id: UUID | None = None,
    report_type: str = "annual",
    variant: str = "impact",
) -> FinancialReportGenerated:
    return FinancialReportGenerated(
        report_id=report_id or uuid4(),
        workspace_id=workspace_id,
        report_type=report_type,
        variant=variant,
        range_start=date(2026, 1, 1),
        range_end=date(2026, 6, 30),
        generated_at=datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc),
        triggered_by="user",
        generated_by_user_id=None,
    )


@pytest.mark.django_db
class TestFinanceSpecialistHandler:
    def test_creates_task_for_report(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_financial_report_generated(event)

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
        assert task.metadata["context"]["report_id"] == str(event.report_id)

        # Title carries the humanised report label.
        assert "Annual" in task.title
        assert "Impact" in task.title

    def test_replayed_event_is_idempotent_on_report_id(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_financial_report_generated(event)
        handle_financial_report_generated(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 1
        )

    def test_different_reports_each_create_their_own_task(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        report_a = uuid4()
        report_b = uuid4()

        handle_financial_report_generated(
            _build_event(workspace_id=workspace.id, report_id=report_a)
        )
        handle_financial_report_generated(
            _build_event(workspace_id=workspace.id, report_id=report_b)
        )

        tasks = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        )
        assert tasks.count() == 2
        report_ids = {t.metadata["context"]["report_id"] for t in tasks}
        assert report_ids == {str(report_a), str(report_b)}

    def test_missing_workspace_logs_does_not_raise(self):
        # Unknown workspace → handler logs and returns; nothing raises.
        handle_financial_report_generated(
            _build_event(workspace_id=uuid4())
        )

    def test_description_carries_the_date_range(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_financial_report_generated(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert "2026-01-01" in task.description
        assert "2026-06-30" in task.description

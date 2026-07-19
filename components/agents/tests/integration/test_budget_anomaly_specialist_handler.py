"""Integration test: ``BudgetAnomalyFindingsDetected`` → Task.

Sibling to ``test_budget_variance_specialist_handler``. Same contract
post-Phase-5 (Agents-as-Teammates migration retired ``AIAction``):

* Per finding, create a Task in "Suggested" with narrative on
  ``Task.description`` and detector context on ``Task.metadata``.
* Idempotency on ``(workspace, source_type,
  metadata.idempotency_key)`` where the key is
  ``period:<period>:category_id:<category_id>``.
* Per-finding failure isolation.

Action List item P0 #7.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from components.agents.application.handlers.budget_anomaly_specialist_handler import (
    ACTION_TYPE,
    AGENT_TYPE,
    DETECTOR_KEY,
    handle_budget_anomaly_findings_detected,
)
from components.budgeting.domain.events.budget_anomaly_findings_detected_event import (
    BudgetAnomalyFindingsDetected,
)


def _build_event(
    *,
    workspace_id: UUID,
    period: str = "2026-06",
    findings=None,
) -> BudgetAnomalyFindingsDetected:
    if findings is None:
        findings = (
            {
                "category_id": 21,
                "category_name": "Education",
                "period": period,
                "current_spend": "1200.00",
                "trailing_mean": "300.00",
                "trailing_stddev": "50.0000",
                "z_score": "18.00",
                "sample_months": 6,
                "impact_score": 100,
            },
            {
                "category_id": 22,
                "category_name": "Transport",
                "period": period,
                "current_spend": "400.00",
                "trailing_mean": "150.00",
                "trailing_stddev": "30.0000",
                "z_score": "8.33",
                "sample_months": 6,
                "impact_score": 100,
            },
        )
    return BudgetAnomalyFindingsDetected(
        workspace_id=workspace_id,
        detector_key=DETECTOR_KEY,
        period=period,
        findings=findings,
    )


@pytest.mark.django_db
class TestBudgetAnomalySpecialistHandler:
    def test_creates_task_per_finding(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_budget_anomaly_findings_detected(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).order_by("metadata__context__category_id")
        )
        assert len(tasks) == 2
        for task in tasks:
            assert task.metadata["agent_type"] == AGENT_TYPE
            assert task.metadata["action_type"] == ACTION_TYPE
            assert task.metadata["detector"] == DETECTOR_KEY
            assert task.metadata["context"]["detector_key"] == DETECTOR_KEY
            assert task.metadata["impact_score"] == 100
            assert task.metadata["severity"] == "high"

        assert any("Education" in t.title for t in tasks)
        assert any("Transport" in t.title for t in tasks)
        # Title shows the z-score formatted with sigma
        assert any("σ" in t.title for t in tasks)

    def test_replayed_event_is_idempotent_on_period_and_category(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_budget_anomaly_findings_detected(event)
        handle_budget_anomaly_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 2
        )

    def test_no_findings_in_event_is_noop(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id, findings=())

        handle_budget_anomaly_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 0
        )

    def test_missing_workspace_logs_warning_does_not_raise(self):
        from uuid import uuid4

        event = _build_event(workspace_id=uuid4())

        # Should not raise even though no workspace exists
        handle_budget_anomaly_findings_detected(event)

"""Integration test: BudgetVarianceFindingsDetected → Task.

Phase 3b mirrors the Phase 3a contract for the variance detector
post-Phase-5 (Agents-as-Teammates migration retired ``AIAction``):

* Per finding, create a Task in "Suggested" with narrative on
  ``Task.description`` and detector context on ``Task.metadata``.
* Idempotency on ``(workspace, source_type,
  metadata.idempotency_key)`` where the key is
  ``period:<period>:category_id:<category_id>``.
* Per-finding failure isolation.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from components.agents.application.handlers.budget_variance_specialist_handler import (
    handle_budget_variance_findings_detected,
)
from components.budgeting.domain.events.budget_variance_findings_detected_event import (
    BudgetVarianceFindingsDetected,
)


def _build_event(
    *,
    workspace_id: UUID,
    period: str = "2026-06",
    findings=None,
) -> BudgetVarianceFindingsDetected:
    if findings is None:
        findings = (
            {
                "category_id": 12,
                "category_name": "Education",
                "period": period,
                "current_spend": "450.00",
                "trailing_mean": "300.00",
                "variance_pct": "0.50",
                "impact_score": 50,
            },
            {
                "category_id": 14,
                "category_name": "Transport",
                "period": period,
                "current_spend": "220.00",
                "trailing_mean": "150.00",
                "variance_pct": "0.47",
                "impact_score": 47,
            },
        )
    return BudgetVarianceFindingsDetected(
        workspace_id=workspace_id,
        detector_key="budget_variance_monthly",
        period=period,
        findings=findings,
    )


@pytest.mark.django_db
class TestBudgetVarianceSpecialistHandler:
    def test_creates_task_per_finding(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_budget_variance_findings_detected(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace,
                source_type="ai.budget_variance_detected",
            ).order_by("metadata__context__category_id")
        )
        assert len(tasks) == 2
        for task in tasks:
            assert task.metadata["action_type"] == "budget_variance_detected"
            assert task.metadata["agent_type"] == "budget_specialist"
            assert task.metadata["detector"] == "budget_variance_monthly"
            assert task.workspace_id == workspace.id

    def test_no_double_create(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_budget_variance_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type="ai.budget_variance_detected",
            ).count()
            == 2
        )

    def test_idempotent_on_period_category_dedup(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_budget_variance_findings_detected(event)
        handle_budget_variance_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type="ai.budget_variance_detected",
            ).count()
            == 2
        )

    def test_handles_workspace_missing_gracefully(self):
        from uuid import uuid4

        event = _build_event(workspace_id=uuid4())
        handle_budget_variance_findings_detected(event)

    def test_per_finding_failure_does_not_void_others(
        self, workspace_factory, monkeypatch
    ):
        from infrastructure.persistence.project.models import Task
        from components.project.application.providers.project_provider import (
            ProjectProvider,
        )

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        original_build = ProjectProvider.build_create_task_use_case
        call_count = {"n": 0}

        def flaky_build():
            use_case = original_build()
            original_execute_fn = use_case.execute

            def execute(*, command):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("transient blip")
                return original_execute_fn(command=command)

            use_case.execute = execute
            return use_case

        monkeypatch.setattr(
            ProjectProvider, "build_create_task_use_case", flaky_build
        )

        handle_budget_variance_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type="ai.budget_variance_detected",
            ).count()
            == 1
        )

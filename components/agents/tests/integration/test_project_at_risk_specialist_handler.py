"""Integration test: ProjectAtRiskFindingsDetected → Task.

Phase 5a (N=3) of the Agents-as-Teammates migration. Post-Phase-5
(``AIAction`` retired), each finding lands as a Kanban Task carrying
narrative on ``Task.description`` and detector context on
``Task.metadata``. Validates the specialist-handler pattern across a
third bounded context (project, not budgeting).
"""
from __future__ import annotations

from uuid import UUID

import pytest

from components.agents.application.handlers.project_at_risk_specialist_handler import (
    handle_project_at_risk_findings_detected,
)
from components.project.domain.events.project_at_risk_findings_detected_event import (
    ProjectAtRiskFindingsDetected,
)


def _build_event(
    *,
    workspace_id: UUID,
    period: str = "2026-06",
    findings=None,
) -> ProjectAtRiskFindingsDetected:
    if findings is None:
        findings = (
            {
                "project_id": "00000000-0000-0000-0000-0000000aaa01",
                "project_title": "Build Greenhouse",
                "team_title": "Operations",
                "overdue_task_count": 4,
                "period": period,
                "impact_score": 50,
            },
            {
                "project_id": "00000000-0000-0000-0000-0000000aaa02",
                "project_title": "Sponsor Onboarding",
                "team_title": "Programs",
                "overdue_task_count": 12,
                "period": period,
                "impact_score": 90,
            },
        )
    return ProjectAtRiskFindingsDetected(
        workspace_id=workspace_id,
        detector_key="project_overdue_task_backlog",
        period=period,
        findings=findings,
    )


@pytest.mark.django_db
class TestProjectAtRiskSpecialistHandler:
    def test_creates_task_per_finding(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_project_at_risk_findings_detected(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace, source_type="ai.project_at_risk"
            ).order_by("metadata__context__project_id")
        )
        assert len(tasks) == 2
        for task in tasks:
            assert task.metadata["action_type"] == "project_at_risk"
            assert task.metadata["agent_type"] == "project_specialist"
            assert task.metadata["detector"] == "project_overdue_task_backlog"
            assert task.workspace_id == workspace.id

    def test_no_double_create(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_project_at_risk_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type="ai.project_at_risk"
            ).count()
            == 2
        )

    def test_idempotent_on_period_project_dedup(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_project_at_risk_findings_detected(event)
        handle_project_at_risk_findings_detected(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type="ai.project_at_risk"
            ).count()
            == 2
        )

    def test_handles_workspace_missing_gracefully(self):
        from uuid import uuid4

        event = _build_event(workspace_id=uuid4())
        handle_project_at_risk_findings_detected(event)

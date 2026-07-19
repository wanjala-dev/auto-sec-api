"""Integration tests for the project-at-risk detector."""

from __future__ import annotations

from datetime import timedelta

import pytest

from components.project.infrastructure.services.at_risk_detector_service import (
    ACTION_TYPE,
    MIN_OVERDUE_TASKS,
    detect_at_risk_projects,
    report_at_risk_projects,
)


def _team(workspace):
    from infrastructure.persistence.team.models import Team

    return Team.objects.create(
        workspace=workspace,
        title="Alpha",
        created_by=workspace.workspace_owner,
        status=Team.ACTIVE,
    )


def _project(workspace, team, *, title):
    from infrastructure.persistence.project.models import Project

    return Project.objects.create(
        workspace=workspace,
        team=team,
        title=title,
        created_by=workspace.workspace_owner,
    )


def _overdue_task(workspace, team, project, *, days_ago: int, status: str = "todo"):
    from django.utils import timezone as django_tz

    from infrastructure.persistence.project.models import Task

    return Task.objects.create(
        workspace=workspace,
        team=team,
        project=project,
        title=f"Task due {days_ago} days ago",
        created_by=workspace.workspace_owner,
        due_date=django_tz.now() - timedelta(days=days_ago),
        status=status,
    )


@pytest.mark.django_db
class TestDetectAtRiskProjects:
    def test_flags_project_with_three_overdue_tasks(self, workspace_factory):
        workspace = workspace_factory()
        team = _team(workspace)
        project = _project(workspace, team, title="Literacy Program")
        for days in (10, 7, 3):
            _overdue_task(workspace, team, project, days_ago=days)
        findings = detect_at_risk_projects(workspace)
        assert len(findings) == 1
        assert findings[0].project_title == "Literacy Program"
        assert findings[0].overdue_task_count == MIN_OVERDUE_TASKS

    def test_does_not_flag_projects_with_fewer_overdue(self, workspace_factory):
        workspace = workspace_factory()
        team = _team(workspace)
        project = _project(workspace, team, title="Small Backlog")
        for days in (5, 3):
            _overdue_task(workspace, team, project, days_ago=days)
        assert detect_at_risk_projects(workspace) == []

    def test_ignores_done_tasks(self, workspace_factory):
        workspace = workspace_factory()
        team = _team(workspace)
        project = _project(workspace, team, title="Completed Backlog")
        for days in (10, 7, 3):
            _overdue_task(workspace, team, project, days_ago=days, status="done")
        assert detect_at_risk_projects(workspace) == []

    def test_ignores_tasks_without_due_date(self, workspace_factory):
        workspace = workspace_factory()
        team = _team(workspace)
        project = _project(workspace, team, title="No Dates")
        from infrastructure.persistence.project.models import Task

        for _ in range(5):
            Task.objects.create(
                workspace=workspace,
                team=team,
                project=project,
                title="Undated task",
                created_by=workspace.workspace_owner,
            )
        assert detect_at_risk_projects(workspace) == []


@pytest.mark.django_db
class TestReportAtRiskProjects:
    def test_emits_one_task_per_at_risk_project(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        team = _team(workspace)
        project = _project(workspace, team, title="Literacy Program")
        for days in (20, 12, 8, 3):
            _overdue_task(workspace, team, project, days_ago=days)
        emitted = report_at_risk_projects(workspace)
        assert emitted == 1
        task = Task.objects.get(
            workspace=workspace,
            source_type=f"ai.{ACTION_TYPE}",
        )
        assert task.metadata["agent_type"] == "project_specialist"
        assert "Literacy Program" in task.title
        assert "4" in task.title

    def test_idempotent_within_a_month(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        team = _team(workspace)
        project = _project(workspace, team, title="Literacy Program")
        for days in (10, 7, 3):
            _overdue_task(workspace, team, project, days_ago=days)
        first = report_at_risk_projects(workspace)
        second = report_at_risk_projects(workspace)
        # report_at_risk_projects returns the number of findings DETECTED in
        # the run; the project is still at risk on the second pass, so it
        # detects 1 again. Idempotency now lives on the handler side, so the
        # real "no duplicate" guarantee is the single persisted Task below.
        assert first == 1
        assert second == 1
        assert (
            Task.objects.filter(
                workspace=workspace,
                source_type=f"ai.{ACTION_TYPE}",
            ).count()
            == 1
        )

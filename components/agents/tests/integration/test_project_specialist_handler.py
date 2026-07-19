"""Integration test: ``ProjectCreated`` → setup-nudge Task on the
agent team Kanban.

Action List item P1 #24. Third specialist through the Phase 3
``SubscriptionRegistry``. Post-Phase-5 (``AIAction`` retired): the
handler writes a Kanban Task carrying narrative on ``Task.description``
and detector context on ``Task.metadata``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from components.agents.application.handlers.project_specialist_handler import (
    ACTION_TYPE,
    AGENT_TYPE,
    DETECTOR_KEY,
    handle_project_created,
)
from components.project.domain.events.project_created_event import (
    ProjectCreated,
)


def _build_event(
    *,
    workspace_id: UUID,
    project_id: UUID | None = None,
    title: str = "Spring Outreach Project",
    team_id: UUID | None = None,
    created_by_id: UUID | None = None,
) -> ProjectCreated:
    return ProjectCreated(
        project_id=project_id or uuid4(),
        workspace_id=workspace_id,
        team_id=team_id,
        created_by_id=created_by_id,
        title=title,
        created_at=datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.django_db
class TestProjectSpecialistHandler:
    def test_creates_setup_nudge_task_for_new_project(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id, title="Spring Outreach"
        )

        handle_project_created(event)

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
        assert task.metadata["context"]["project_id"] == str(event.project_id)
        assert task.metadata["context"]["project_title"] == "Spring Outreach"

        assert "Set up: Spring Outreach" in task.title

    def test_replayed_event_is_idempotent_on_project_id(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_project_created(event)
        handle_project_created(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 1
        )

    def test_two_projects_each_get_their_own_task(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        handle_project_created(_build_event(workspace_id=workspace.id))
        handle_project_created(_build_event(workspace_id=workspace.id))

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 2
        )

    def test_untitled_project_uses_fallback(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id, title="   ")

        handle_project_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task is not None
        assert "Untitled project" in task.title

    def test_missing_workspace_id_skips_silently(self):
        from infrastructure.persistence.project.models import Task

        event = ProjectCreated(
            project_id=uuid4(),
            workspace_id=None,
            team_id=None,
            created_by_id=None,
            title="Orphan project",
            created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        )

        handle_project_created(event)

        # No workspace → no task; handler logs and returns.
        assert Task.objects.filter(source_type=f"ai.{ACTION_TYPE}").count() == 0

    def test_unknown_workspace_uuid_skips_silently(self):
        from infrastructure.persistence.project.models import Task

        handle_project_created(_build_event(workspace_id=uuid4()))

        assert Task.objects.filter(source_type=f"ai.{ACTION_TYPE}").count() == 0

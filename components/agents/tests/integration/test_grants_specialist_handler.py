"""Integration test: ``OpportunityCreated`` → triage Task on the agent
team Kanban.

Action List item P1 #23. Fourth specialist through Phase 3.
Post-Phase-5: ``AIAction`` is gone; everything writes a Kanban Task
with narrative on ``Task.description`` and detector context on
``Task.metadata``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest

from components.agents.application.handlers.grants_specialist_handler import (
    ACTION_TYPE,
    AGENT_TYPE,
    DETECTOR_KEY,
    handle_opportunity_created,
)
from components.grants.domain.events.opportunity_created_event import (
    OpportunityCreated,
)


def _build_event(
    *,
    workspace_id: UUID,
    opportunity_id: UUID | None = None,
    title: str = "Spring Education Grant",
    funder_id: UUID | None = None,
    submission_deadline: date | None = date(2026, 9, 1),
    actor_id: int | None = 1,
) -> OpportunityCreated:
    return OpportunityCreated(
        opportunity_id=opportunity_id or uuid4(),
        workspace_id=workspace_id,
        funder_id=funder_id,
        actor_id=actor_id,
        title=title,
        submission_deadline=submission_deadline,
        created_at=datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.django_db
class TestGrantsSpecialistHandler:
    def test_creates_triage_task_for_new_opportunity(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id, title="Spring Education Grant"
        )

        handle_opportunity_created(event)

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
        assert task.metadata["context"]["opportunity_id"] == str(
            event.opportunity_id
        )
        assert task.metadata["context"]["opportunity_title"] == (
            "Spring Education Grant"
        )
        assert "Pursue: Spring Education Grant" in task.title

    def test_replayed_event_is_idempotent_on_opportunity_id(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_opportunity_created(event)
        handle_opportunity_created(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 1
        )

    def test_two_opportunities_each_get_their_own_task(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        handle_opportunity_created(_build_event(workspace_id=workspace.id))
        handle_opportunity_created(_build_event(workspace_id=workspace.id))

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 2
        )

    def test_no_deadline_uses_lower_impact_score(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id, submission_deadline=None
        )

        handle_opportunity_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task.metadata["impact_score"] == 40

    def test_deadline_bumps_impact_score(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id,
            submission_deadline=date(2026, 9, 1),
        )

        handle_opportunity_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task.metadata["impact_score"] == 60
        # Description surfaces the deadline so the operator sees it at a glance.
        assert "2026-09-01" in task.description

    def test_untitled_opportunity_uses_fallback(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id, title="   ")

        handle_opportunity_created(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task is not None
        assert "Untitled opportunity" in task.title

    def test_missing_workspace_skips_silently(self):
        from infrastructure.persistence.project.models import Task

        event = OpportunityCreated(
            opportunity_id=uuid4(),
            workspace_id=uuid4(),  # unknown
            funder_id=None,
            actor_id=None,
            title="Orphan opportunity",
            submission_deadline=None,
            created_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        )

        handle_opportunity_created(event)

        assert (
            Task.objects.filter(source_type=f"ai.{ACTION_TYPE}").count()
            == 0
        )

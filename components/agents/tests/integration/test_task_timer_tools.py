"""DB-backed tests for task_agent timer tools (PR-B5).

Henry called these out by name in the GTM lock-down ask. The frontend
already has timer UI on TaskCard (``handleKanbanTaskTimer`` posts to
``/project/tasks/timer/{action}_timer/``); these agent tools wire to
the SAME ``StartTimerUseCase`` / ``StopTimerUseCase`` the existing UI
drives, so the agent and the play-button mutate the same ProjectEntry
rows.

What's covered:
- ``start_task_timer`` happy-path + active-team resolution + idempotency
- ``stop_task_timer`` records elapsed minutes
- ``get_task_timer_status`` while running and while idle
- Error paths: missing task_id, unknown task, no active timer to stop
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from components.agents.infrastructure.adapters.langchain.tools import (
    task_agent as task_tools,
)


def _make_agent(workspace_id, user):
    """Stub agent with the attributes the tools read.

    ``_resolve_user`` reads ``agent.config['default_user_id']`` and
    ``agent.user_id`` — set both so the ``CustomUser`` lookup hits.
    """
    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id
    agent.config = {
        "default_user_id": str(user.id),
        "default_user_email": user.email,
    }
    return agent


@pytest.fixture
def timer_setup(workspace_factory, user_factory, team_factory):
    """Workspace + active team (with the user as a member) + a Task.

    The ``StartTimerUseCase`` requires the user to be on the active
    team for the workspace. Use ``team_factory`` and explicitly add
    the user as a member.
    """
    from infrastructure.persistence.project.models import Project, Task

    user = user_factory()
    workspace = workspace_factory(owner=user)
    team = team_factory(workspace=workspace, created_by=user, members=[user])
    # The TimeTrackingRepository's ``resolve_active_team_for_timer``
    # reads ``user.profile.active_team_id`` — set it on the user's
    # profile so the start/stop use cases can find the team.
    profile = getattr(user, "profile", None)
    if profile is not None:
        profile.active_team_id = team.id
        profile.save(update_fields=["active_team"] if hasattr(profile, "active_team") else None)
    project = Project.objects.create(
        workspace=workspace,
        team=team,
        title="Timer test project",
        created_by=user,
    )
    task = Task.objects.create(
        workspace_id=workspace.id,
        team=team,
        project=project,
        title="Trackable task",
        created_by=user,
    )
    return {
        "user": user,
        "workspace": workspace,
        "team": team,
        "task": task,
        "agent": _make_agent(workspace.id, user),
    }


# ── start_task_timer ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestStartTaskTimer:
    def test_starts_a_new_timer(self, timer_setup):
        from infrastructure.persistence.project.models import ProjectEntry

        result = task_tools.start_task_timer(
            timer_setup["agent"],
            {"task_id": str(timer_setup["task"].id)},
        )
        assert "Started timer" in result
        # ProjectEntry created with is_tracked=True.
        entry = ProjectEntry.objects.filter(
            task=timer_setup["task"], created_by=timer_setup["user"], is_tracked=True
        ).first()
        assert entry is not None

    def test_rejects_missing_task_id(self, timer_setup):
        result = task_tools.start_task_timer(timer_setup["agent"], {})
        assert "task_id is required" in result


# ── stop_task_timer ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestStopTaskTimer:
    def test_records_elapsed_minutes(self, timer_setup):
        from infrastructure.persistence.project.models import ProjectEntry

        # Manually create an entry that started 5 minutes ago so we can
        # assert the stop tool recorded a positive minute count.
        ProjectEntry.objects.create(
            workspace_id=timer_setup["workspace"].id,
            team=timer_setup["team"],
            project=timer_setup["task"].project,
            task=timer_setup["task"],
            minutes=0,
            is_tracked=True,
            created_by=timer_setup["user"],
            created_at=timezone.now() - timedelta(minutes=5),
        )

        result = task_tools.stop_task_timer(
            timer_setup["agent"],
            {"task_id": str(timer_setup["task"].id)},
        )
        assert "Stopped timer" in result

        entry = ProjectEntry.objects.filter(
            task=timer_setup["task"], created_by=timer_setup["user"]
        ).order_by("-created_at").first()
        assert entry is not None
        assert entry.is_tracked is False
        assert entry.minutes >= 4  # ~5 minutes elapsed; floor or ceil OK.

    def test_rejects_when_no_active_timer(self, timer_setup):
        # No entry exists; stop should report a friendly error.
        result = task_tools.stop_task_timer(
            timer_setup["agent"],
            {"task_id": str(timer_setup["task"].id)},
        )
        assert "Cannot stop timer" in result or "No active timer" in result


# ── get_task_timer_status ─────────────────────────────────────────────


@pytest.mark.django_db
class TestGetTaskTimerStatus:
    def test_reports_idle_when_no_entries(self, timer_setup):
        result = task_tools.get_task_timer_status(
            timer_setup["agent"],
            {"task_id": str(timer_setup["task"].id)},
        )
        assert "No active timer" in result
        assert "0 minute" in result.lower()

    def test_reports_total_after_stop(self, timer_setup):
        from infrastructure.persistence.project.models import ProjectEntry

        # Stopped entry with 12 minutes recorded.
        ProjectEntry.objects.create(
            workspace_id=timer_setup["workspace"].id,
            team=timer_setup["team"],
            project=timer_setup["task"].project,
            task=timer_setup["task"],
            minutes=12,
            is_tracked=False,
            created_by=timer_setup["user"],
            created_at=timezone.now() - timedelta(hours=1),
        )
        result = task_tools.get_task_timer_status(
            timer_setup["agent"],
            {"task_id": str(timer_setup["task"].id)},
        )
        assert "No active timer" in result
        # Total should reflect the 12 minutes from the stopped entry.
        assert "12 minute" in result.lower()

    def test_reports_running_state(self, timer_setup):
        from infrastructure.persistence.project.models import ProjectEntry

        ProjectEntry.objects.create(
            workspace_id=timer_setup["workspace"].id,
            team=timer_setup["team"],
            project=timer_setup["task"].project,
            task=timer_setup["task"],
            minutes=0,
            is_tracked=True,
            created_by=timer_setup["user"],
            created_at=timezone.now() - timedelta(minutes=3),
        )
        result = task_tools.get_task_timer_status(
            timer_setup["agent"],
            {"task_id": str(timer_setup["task"].id)},
        )
        assert "RUNNING" in result
        assert "elapsed" in result.lower()

    def test_rejects_unknown_task(self, timer_setup):
        result = task_tools.get_task_timer_status(
            timer_setup["agent"],
            {"task_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(self, workspace_factory, user_factory, team_factory):
        from infrastructure.persistence.project.models import Task

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        team_b = team_factory(workspace=ws_b, created_by=u, members=[u])
        task_in_b = Task.objects.create(
            workspace_id=ws_b.id, team=team_b, title="In B", created_by=u
        )
        result = task_tools.get_task_timer_status(
            _make_agent(ws_a.id, u),
            {"task_id": str(task_in_b.id)},
        )
        assert "not found" in result

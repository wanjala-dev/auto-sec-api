"""Integration — board reads window every lane; lanes page via load-more.

Root fix for the unreadable 9k-card intake board: the columns-with-tasks
endpoints used to serialize EVERY task of EVERY lane into one response
(10.8MB / 30s+ for the demo's "AI Findings" board — a hard 504 at the
ingress), violating performance.md §11 (pagination is not optional).

Contract under test:

* Board reads (``ColumnsView`` team/project routes) attach at most
  ``tasks_limit`` tasks per column (default
  ``DEFAULT_COLUMN_TASKS_LIMIT``, clamped to ``MAX_COLUMN_TASKS_LIMIT``)
  in board order, plus ``tasks_total`` / ``tasks_has_more`` per column.
* ``GET /project/columns/<id>/tasks/`` pages the remainder of one lane with
  the same ordering — consecutive windows never skip or duplicate cards.
* Soft-deleted columns are excluded by the QUERY (they used to be fully
  serialized and then discarded).
* Query-count regression: the board read's query count is CONSTANT with
  respect to how many tasks sit in its lanes (performance.md §1 —
  repositories eager-load what the serializer reads).
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from components.workspace.application.ports.column_query_port import (
    DEFAULT_COLUMN_TASKS_LIMIT,
    MAX_COLUMN_TASKS_LIMIT,
)
from infrastructure.persistence.project.models import Column, Project, Task

pytestmark = pytest.mark.django_db


def _column(workspace, team, user, *, title="To Do", order=0, project=None, is_deleted=False):
    return Column.objects.create(
        workspace=workspace,
        team=team,
        title=title,
        order=order,
        project=project,
        created_by=user,
        is_deleted=is_deleted,
    )


def _tasks(workspace, team, user, column, count, *, project=None, start=0):
    return [
        Task.objects.create(
            workspace=workspace,
            team=team,
            column=column,
            project=project,
            title=f"Task {start + i}",
            order=start + i,
            created_by=user,
        )
        for i in range(count)
    ]


@pytest.fixture
def board(workspace_factory, team_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return owner, workspace, team


def _team_board_url(team, workspace):
    return reverse(
        "project:columns-by-team-workspace",
        kwargs={"team_id": team.id, "workspace_id": workspace.id},
    )


class TestBoardReadWindowsLanes:
    def test_lane_is_windowed_with_total_and_has_more(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, 7)

        api_client.force_authenticate(owner)
        response = api_client.get(_team_board_url(team, workspace), {"tasks_limit": 5})

        assert response.status_code == 200
        (lane,) = response.data["data"]
        assert len(lane["tasks"]) == 5
        assert lane["tasks_total"] == 7
        assert lane["tasks_has_more"] is True
        # Board order: ('order', 'created_at') — the window is the lane's head.
        assert [t["title"] for t in lane["tasks"]] == [f"Task {i}" for i in range(5)]

    def test_default_window_applies_without_param(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, DEFAULT_COLUMN_TASKS_LIMIT + 3)

        api_client.force_authenticate(owner)
        response = api_client.get(_team_board_url(team, workspace))

        (lane,) = response.data["data"]
        assert len(lane["tasks"]) == DEFAULT_COLUMN_TASKS_LIMIT
        assert lane["tasks_total"] == DEFAULT_COLUMN_TASKS_LIMIT + 3
        assert lane["tasks_has_more"] is True

    def test_tasks_limit_is_clamped(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, 3)

        api_client.force_authenticate(owner)
        # Absurd/invalid values fall back to sane windows — never unbounded.
        for raw in ("999999", "0", "-5", "junk"):
            response = api_client.get(_team_board_url(team, workspace), {"tasks_limit": raw})
            (lane,) = response.data["data"]
            assert len(lane["tasks"]) <= MAX_COLUMN_TASKS_LIMIT
            assert lane["tasks_total"] == 3

    def test_soft_deleted_column_excluded_at_query(self, api_client, board):
        owner, workspace, team = board
        _column(workspace, team, owner, title="Live", order=0)
        dead = _column(workspace, team, owner, title="Dead", order=1, is_deleted=True)
        _tasks(workspace, team, owner, dead, 4)

        api_client.force_authenticate(owner)
        response = api_client.get(_team_board_url(team, workspace))

        titles = [c["title"] for c in response.data["data"]]
        assert titles == ["Live"]

    def test_project_board_route_windows_too(self, api_client, board):
        owner, workspace, team = board
        project = Project.objects.create(workspace=workspace, team=team, title="Intake", created_by=owner)
        column = _column(workspace, team, owner, project=project)
        _tasks(workspace, team, owner, column, 6, project=project)

        api_client.force_authenticate(owner)
        url = reverse(
            "project:columns-by-project-team-workspace",
            kwargs={"project_id": project.id, "team_id": team.id, "workspace_id": workspace.id},
        )
        response = api_client.get(url, {"tasks_limit": 4})

        (lane,) = response.data["data"]
        assert len(lane["tasks"]) == 4
        assert lane["tasks_total"] == 6
        assert lane["tasks_has_more"] is True


class TestColumnTasksLoadMore:
    def test_pages_are_contiguous_without_skips_or_dupes(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, 9)

        api_client.force_authenticate(owner)
        url = reverse("project:column-tasks", kwargs={"column_id": column.id})

        seen = []
        offset = 0
        while True:
            response = api_client.get(url, {"offset": offset, "limit": 4})
            assert response.status_code == 200
            meta = response.data["meta"]
            page_titles = [t["title"] for t in response.data["data"]]
            seen.extend(page_titles)
            assert meta["total"] == 9
            if not meta["has_more"]:
                break
            offset += len(page_titles)

        assert seen == [f"Task {i}" for i in range(9)]

    def test_offset_beyond_end_is_empty(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, 2)

        api_client.force_authenticate(owner)
        url = reverse("project:column-tasks", kwargs={"column_id": column.id})
        response = api_client.get(url, {"offset": 50, "limit": 10})

        assert response.status_code == 200
        assert response.data["data"] == []
        assert response.data["meta"]["has_more"] is False

    def test_archived_tasks_excluded(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, 2)
        Task.objects.create(
            workspace=workspace,
            team=team,
            column=column,
            title="Trashed",
            status=Task.ARCHIVED,
            created_by=owner,
        )

        api_client.force_authenticate(owner)
        url = reverse("project:column-tasks", kwargs={"column_id": column.id})
        response = api_client.get(url)

        assert response.data["meta"]["total"] == 2
        assert [t["title"] for t in response.data["data"]] == ["Task 0", "Task 1"]

    def test_requires_membership(self, api_client, board, user_factory):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        outsider = user_factory()

        api_client.force_authenticate(outsider)
        url = reverse("project:column-tasks", kwargs={"column_id": column.id})
        response = api_client.get(url)

        assert response.status_code == 403


class TestBoardReadQueryCount:
    """Query count must be constant w.r.t. how many tasks the lanes hold."""

    def _query_count(self, api_client, url, params):
        with CaptureQueriesContext(connection) as ctx:
            response = api_client.get(url, params)
        assert response.status_code == 200
        return len(ctx.captured_queries), response

    def test_team_board_read_is_constant_in_task_count(self, api_client, board):
        owner, workspace, team = board
        columns = [_column(workspace, team, owner, title=f"Lane {i}", order=i) for i in range(3)]
        for column in columns:
            _tasks(workspace, team, owner, column, 4)

        api_client.force_authenticate(owner)
        url = _team_board_url(team, workspace)
        # Warm-up: content types / permission rows cached by the first call.
        api_client.get(url, {"tasks_limit": 10})

        baseline, _ = self._query_count(api_client, url, {"tasks_limit": 10})

        for column in columns:
            _tasks(workspace, team, owner, column, 6, start=4)

        grown, response = self._query_count(api_client, url, {"tasks_limit": 10})

        assert grown == baseline, (
            f"board read query count grew with task count ({baseline} -> {grown}); "
            "a per-row query crept back into TaskSerializer or the repository "
            "window lost an eager-load"
        )
        assert all(len(lane["tasks"]) == 10 for lane in response.data["data"])

    def test_project_board_read_is_constant_in_task_count(self, api_client, board):
        # The project-board case exercises TaskSerializer's inline project
        # serialization — cached per distinct project, it must not re-run
        # ProjectSerializer's ~5 queries per CARD.
        owner, workspace, team = board
        project = Project.objects.create(workspace=workspace, team=team, title="Intake", created_by=owner)
        column = _column(workspace, team, owner, project=project)
        _tasks(workspace, team, owner, column, 4, project=project)

        api_client.force_authenticate(owner)
        url = reverse(
            "project:columns-by-project-team-workspace",
            kwargs={"project_id": project.id, "team_id": team.id, "workspace_id": workspace.id},
        )
        api_client.get(url, {"tasks_limit": 20})

        baseline, _ = self._query_count(api_client, url, {"tasks_limit": 20})

        _tasks(workspace, team, owner, column, 8, project=project, start=4)

        grown, response = self._query_count(api_client, url, {"tasks_limit": 20})

        assert grown == baseline, f"project board query count grew with task count ({baseline} -> {grown})"
        (lane,) = response.data["data"]
        assert len(lane["tasks"]) == 12

    def test_column_tasks_page_is_constant_in_page_size_growth(self, api_client, board):
        owner, workspace, team = board
        column = _column(workspace, team, owner)
        _tasks(workspace, team, owner, column, 3)

        api_client.force_authenticate(owner)
        url = reverse("project:column-tasks", kwargs={"column_id": column.id})
        api_client.get(url, {"limit": 10})

        baseline, _ = self._query_count(api_client, url, {"limit": 10})

        _tasks(workspace, team, owner, column, 5, start=3)

        grown, response = self._query_count(api_client, url, {"limit": 10})

        assert grown == baseline, f"column tasks page query count grew with task count ({baseline} -> {grown})"
        assert len(response.data["data"]) == 8

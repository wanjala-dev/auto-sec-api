"""Query-count regression guard for the view-board read (ADR 0030 P2a).

performance.md §1: the board read's query count must be CONSTANT with respect
to how many tasks sit in its lanes — the repository window eager-loads
everything ``TaskSerializer`` reads (2 queries per lane: count + window, plus
the two prefetches, all independent of row count). Copies the established
``test_*query_count.py`` shape: warm up, capture a baseline, grow the data,
assert the count did not move (never a brittle absolute number).
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from components.project.domain.workflow_status_vocabulary import CANONICAL_STATUSES
from infrastructure.persistence.project.models import BoardView, Column, Project, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded_board(workspace_factory, team_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    columns = {}
    for name, _category, order in CANONICAL_STATUSES:
        columns[name] = Column.objects.create(
            workspace=workspace, team=team, project=None, title=name, order=order, created_by=owner
        )
    return owner, workspace, team, columns


def _tasks(workspace, team, owner, column, count, *, project=None, start=0):
    for i in range(count):
        Task.objects.create(
            workspace=workspace,
            team=team,
            column=column,
            project=project,
            title=f"Task {start + i}",
            order=start + i,
            created_by=owner,
        )


def _view(workspace, team, *, slug="board", filter=None):
    return BoardView.objects.create(
        workspace=workspace, team=team, name=slug, slug=slug, filter=filter or {}, is_system=True
    )


def _query_count(api_client, url, params):
    with CaptureQueriesContext(connection) as ctx:
        response = api_client.get(url, params)
    assert response.status_code == 200
    return len(ctx.captured_queries), response


class TestViewBoardQueryCount:
    def test_view_board_read_is_constant_in_task_count(self, api_client, seeded_board):
        owner, workspace, team, columns = seeded_board
        for name in ("Todo", "In Progress", "Complete"):
            _tasks(workspace, team, owner, columns[name], 4)
        view = _view(workspace, team)
        url = reverse("project:view-board", kwargs={"view_id": view.id})

        api_client.force_authenticate(owner)
        # Warm-up: content types / permission rows cached by the first call.
        api_client.get(url, {"tasks_limit": 10})

        baseline, _ = _query_count(api_client, url, {"tasks_limit": 10})

        for name in ("Todo", "In Progress", "Complete"):
            _tasks(workspace, team, owner, columns[name], 6, start=4)

        grown, response = _query_count(api_client, url, {"tasks_limit": 10})

        assert grown == baseline, (
            f"view board query count grew with task count ({baseline} -> {grown}); "
            "a per-row query crept back into TaskSerializer or the lane window "
            "lost an eager-load"
        )
        lanes = {lane["name"]: lane for lane in response.data["data"]["lanes"]}
        assert all(len(lanes[n]["tasks"]) == 10 for n in ("Todo", "In Progress", "Complete"))

    def test_filtered_view_board_read_is_constant_in_task_count(self, api_client, seeded_board):
        # The project-filtered case exercises TaskSerializer's inline project
        # serialization — cached per distinct project, it must not re-run per CARD.
        owner, workspace, team, columns = seeded_board
        project = Project.objects.create(workspace=workspace, team=team, title="Intake", created_by=owner)
        _tasks(workspace, team, owner, columns["Todo"], 4, project=project)
        view = _view(workspace, team, slug=f"project-{project.id}", filter={"project": str(project.id)})
        url = reverse("project:view-board", kwargs={"view_id": view.id})

        api_client.force_authenticate(owner)
        api_client.get(url, {"tasks_limit": 20})

        baseline, _ = _query_count(api_client, url, {"tasks_limit": 20})

        _tasks(workspace, team, owner, columns["Todo"], 8, project=project, start=4)

        grown, response = _query_count(api_client, url, {"tasks_limit": 20})

        assert grown == baseline, f"filtered view board query count grew with task count ({baseline} -> {grown})"
        lanes = {lane["name"]: lane for lane in response.data["data"]["lanes"]}
        assert len(lanes["Todo"]["tasks"]) == 12

    def test_lane_pager_is_constant_in_task_count(self, api_client, seeded_board):
        owner, workspace, team, columns = seeded_board
        _tasks(workspace, team, owner, columns["Todo"], 3)
        view = _view(workspace, team)
        status_id = columns["Todo"].workflow_status_id
        url = reverse("project:view-lane-tasks", kwargs={"view_id": view.id, "status_id": status_id})

        api_client.force_authenticate(owner)
        api_client.get(url, {"limit": 10})

        baseline, _ = _query_count(api_client, url, {"limit": 10})

        _tasks(workspace, team, owner, columns["Todo"], 5, start=3)

        grown, response = _query_count(api_client, url, {"limit": 10})

        assert grown == baseline, f"view lane pager query count grew with task count ({baseline} -> {grown})"
        assert len(response.data["data"]) == 8

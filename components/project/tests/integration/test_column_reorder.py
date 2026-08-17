"""``ColumnReorderView`` (POST /project/columns/reorder/) — first test pack.

The endpoint has existed since the fork (and works — verified live, QA report
2026-08-16 F2) but carried ZERO tests. Covers: happy path persists, cross-team
batch rejected, non-member forbidden, and atomicity (a partial failure changes
nothing).
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from infrastructure.persistence.project.models import Column
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_URL = reverse("project:column-reorder")


def _board(workspace_factory, team_factory, titles=("Backlog", "Todo", "In Progress")):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    columns = [
        Column.objects.create(
            team=team, workspace=workspace, project=None, title=title, order=index + 1, created_by=owner
        )
        for index, title in enumerate(titles)
    ]
    return workspace, owner, team, columns


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _orders(columns) -> list[int]:
    return [Column.objects.get(pk=column.pk).order for column in columns]


class TestColumnReorder:
    def test_happy_path_persists_new_order(self, workspace_factory, team_factory):
        workspace, owner, team, (backlog, todo, in_progress) = _board(workspace_factory, team_factory)

        response = _client(owner).post(
            _URL,
            {
                "updates": [
                    {"id": todo.id, "order": 1},
                    {"id": backlog.id, "order": 2},
                    {"id": in_progress.id, "order": 3},
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _orders([todo, backlog, in_progress]) == [1, 2, 3]
        titles = list(
            Column.objects.filter(team=team, project__isnull=True)
            .order_by("order", "id")
            .values_list("title", flat=True)
        )
        assert titles == ["Todo", "Backlog", "In Progress"]

    def test_cross_team_batch_rejected(self, workspace_factory, team_factory):
        workspace, owner, team, (backlog, todo, _) = _board(workspace_factory, team_factory)
        other_team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        foreign = Column.objects.create(
            team=other_team, workspace=workspace, project=None, title="Elsewhere", order=1, created_by=owner
        )

        response = _client(owner).post(
            _URL,
            {"updates": [{"id": backlog.id, "order": 2}, {"id": foreign.id, "order": 1}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _orders([backlog, foreign]) == [1, 1], "a rejected batch must change nothing"

    def test_workspace_member_outside_the_team_is_forbidden(self, workspace_factory, team_factory, user_factory):
        workspace, owner, team, (backlog, todo, _) = _board(workspace_factory, team_factory)
        # An ACTIVE plain member of the workspace (so the workspace gate
        # passes) who is NOT on the team and holds no admin bypass.
        outsider = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=outsider,
            role=WorkspaceMembership.Role.MEMBER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        response = _client(outsider).post(
            _URL,
            {"updates": [{"id": backlog.id, "order": 2}, {"id": todo.id, "order": 1}]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert _orders([backlog, todo]) == [1, 2]

    def test_complete_outsider_is_forbidden(self, workspace_factory, team_factory, user_factory):
        workspace, owner, team, (backlog, todo, _) = _board(workspace_factory, team_factory)
        stranger = user_factory()

        response = _client(stranger).post(
            _URL,
            {"updates": [{"id": backlog.id, "order": 2}, {"id": todo.id, "order": 1}]},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert _orders([backlog, todo]) == [1, 2]

    def test_unknown_column_in_batch_changes_nothing(self, workspace_factory, team_factory):
        workspace, owner, team, (backlog, todo, _) = _board(workspace_factory, team_factory)

        response = _client(owner).post(
            _URL,
            {"updates": [{"id": backlog.id, "order": 99}, {"id": 999_999_999, "order": 1}]},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert _orders([backlog, todo]) == [1, 2]

    def test_partial_write_failure_rolls_back_everything(self, workspace_factory, team_factory, monkeypatch):
        """Atomicity: if the Nth write blows up, the first N-1 must roll back."""
        workspace, owner, team, (backlog, todo, in_progress) = _board(workspace_factory, team_factory)

        original_save = Column.save
        state = {"order_writes": 0}

        def flaky_save(self, *args, **kwargs):
            update_fields = kwargs.get("update_fields") or ()
            if "order" in update_fields:
                state["order_writes"] += 1
                if state["order_writes"] == 2:
                    raise RuntimeError("simulated write failure")
            return original_save(self, *args, **kwargs)

        monkeypatch.setattr(Column, "save", flaky_save)

        payload = {
            "updates": [
                {"id": backlog.id, "order": 3},
                {"id": todo.id, "order": 1},
                {"id": in_progress.id, "order": 2},
            ]
        }
        try:
            response = _client(owner).post(_URL, payload, format="json")
        except RuntimeError:
            response = None  # the error propagated through the test client
        if response is not None:
            assert response.status_code >= 500

        assert state["order_writes"] == 2, "the failure must have fired mid-batch"
        assert _orders([backlog, todo, in_progress]) == [1, 2, 3], "no partial order may survive the rollback"

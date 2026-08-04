"""Integration — board reads exclude soft-deleted (ARCHIVED) tasks.

Regression for the recycle-bin loop: trashing a task sets ``status=ARCHIVED``
but keeps its column FK, so the board's columns read (``ColumnSerializer``)
and the project read (``ProjectGetSerializer``) must exclude it — otherwise a
deleted card sits in the recycle bin AND still renders on the board, and every
board refetch resurrects it in the UI. ``project_repository``'s task list
reads already excluded ARCHIVED; these serializer paths did not.
"""

from __future__ import annotations

import pytest

from components.project.mappers.rest.project_serializers import (
    ColumnSerializer,
    ProjectGetSerializer,
)
from infrastructure.persistence.project.models import Column, Project, Task

pytestmark = pytest.mark.django_db


def _column(workspace, team, user, *, title="To Do"):
    return Column.objects.create(workspace=workspace, team=team, title=title, created_by=user)


def _task(workspace, team, user, column=None, *, title="QA Task", status=Task.TODO, project=None):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        column=column,
        project=project,
        title=title,
        status=status,
        created_by=user,
    )


class TestBoardReadsExcludeArchived:
    def test_column_serializer_excludes_archived_tasks(self, workspace_factory, team_factory, user_factory) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        column = _column(workspace, team, owner)
        live = _task(workspace, team, owner, column, title="Live")
        _task(workspace, team, owner, column, title="Trashed", status=Task.ARCHIVED)

        data = ColumnSerializer(column).data

        titles = [task["title"] for task in data["tasks"]]
        assert titles == ["Live"]
        assert str(data["tasks"][0]["pk"]) == str(live.pk)

    def test_project_get_serializer_excludes_archived_tasks(self, workspace_factory, team_factory, user_factory) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        project = Project.objects.create(workspace=workspace, team=team, title="QA Project", created_by=owner)
        column = _column(workspace, team, owner)
        _task(workspace, team, owner, column, title="Live", project=project)
        _task(
            workspace,
            team,
            owner,
            column,
            title="Trashed",
            status=Task.ARCHIVED,
            project=project,
        )

        data = ProjectGetSerializer(project).data

        titles = [task["title"] for task in data["tasks"]]
        assert titles == ["Live"]

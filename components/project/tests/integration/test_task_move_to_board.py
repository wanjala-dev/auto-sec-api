"""Integration: POST /api/v1/project/tasks/<task_id>/move-board/.

Moving a task to a DIFFERENT board must reassign its team + project + column
atomically (batch-move only touches the column FK). These tests prove:

* team + project + column are all reassigned to the destination board;
* the destination is derived from the target column (the three stay consistent);
* an invalid destination column → 404;
* a cross-workspace destination → 400;
* permission is enforced against the DESTINATION board (non-member → 403).
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from infrastructure.persistence.project.models import Column, Project, Task
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def _user(username):
    user = CustomUser.objects.create_user(
        username=username,
        email="%s@example.com" % username,
        password="pass1234",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _workspace(owner, name):
    return Workspace.objects.create(workspace_name=name, workspace_owner=owner, status="active")


def _team(workspace, owner, title, members=()):
    team = Team.objects.create(workspace=workspace, title=title, created_by=owner)
    team.members.add(owner, *members)
    return team


def _project(workspace, team, owner, title):
    return Project.objects.create(workspace=workspace, team=team, title=title, created_by=owner)


def _column(workspace, team, owner, title, project=None):
    return Column.objects.create(workspace=workspace, team=team, title=title, created_by=owner, project=project)


def _task(workspace, team, owner, column, project=None, title="Card"):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        project=project,
        column=column,
        title=title,
        created_by=owner,
    )


def test_move_reassigns_team_project_and_column_atomically():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")

    src_team = _team(workspace, owner, "Source Team")
    src_project = _project(workspace, src_team, owner, "Source Project")
    src_column = _column(workspace, src_team, owner, "Src To Do", project=src_project)
    task = _task(workspace, src_team, owner, src_column, project=src_project)

    dest_team = _team(workspace, owner, "Dest Team")
    dest_project = _project(workspace, dest_team, owner, "Dest Project")
    dest_column = _column(workspace, dest_team, owner, "Dest To Do", project=dest_project)

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": dest_column.pk, "order": 3}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["success"] is True

    task.refresh_from_db()
    assert task.team_id == dest_team.id
    assert task.project_id == dest_project.id
    assert task.column_id == dest_column.id
    assert task.order == 3


def test_move_to_team_level_board_clears_project():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")

    src_team = _team(workspace, owner, "Source Team")
    src_project = _project(workspace, src_team, owner, "Source Project")
    src_column = _column(workspace, src_team, owner, "Src", project=src_project)
    task = _task(workspace, src_team, owner, src_column, project=src_project)

    dest_team = _team(workspace, owner, "Dest Team")
    # Team-level board column (no project).
    dest_column = _column(workspace, dest_team, owner, "Dest", project=None)

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": dest_column.pk}, format="json")

    assert response.status_code == status.HTTP_200_OK
    task.refresh_from_db()
    assert task.team_id == dest_team.id
    assert task.project_id is None
    assert task.column_id == dest_column.id


def test_move_requires_target_column():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team")
    column = _column(workspace, team, owner, "Col")
    task = _task(workspace, team, owner, column)

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_move_to_nonexistent_column_returns_404():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team")
    column = _column(workspace, team, owner, "Col")
    task = _task(workspace, team, owner, column)

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": 999999}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_move_to_column_in_different_workspace_returns_400():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team")
    column = _column(workspace, team, owner, "Col")
    task = _task(workspace, team, owner, column)

    owner2 = _user("owner2")
    other_ws = _workspace(owner2, "Other")
    other_team = _team(other_ws, owner2, "Other Team")
    other_column = _column(other_ws, other_team, owner2, "Other Col")

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": other_column.pk}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    task.refresh_from_db()
    assert task.column_id == column.id  # unchanged


def test_move_enforces_permission_on_destination_board():
    # ``mover`` belongs to the SOURCE board but NOT the destination team.
    owner = _user("owner")
    mover = _user("mover")
    workspace = _workspace(owner, "Primary")

    src_team = _team(workspace, owner, "Source Team", members=[mover])
    src_column = _column(workspace, src_team, owner, "Src")
    task = _task(workspace, src_team, owner, src_column)

    dest_team = _team(workspace, owner, "Dest Team")  # mover is NOT a member
    dest_column = _column(workspace, dest_team, owner, "Dest")

    client = APIClient()
    client.force_authenticate(user=mover)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": dest_column.pk}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    task.refresh_from_db()
    assert task.team_id == src_team.id  # unchanged
    assert task.column_id == src_column.id


def test_move_enforces_permission_on_source_board():
    # ``mover`` belongs to the DESTINATION team but NOT the source team — they
    # must not be able to move a card OUT of a board they can't mutate
    # (mirrors the batch-move source-team check).
    owner = _user("owner")
    mover = _user("mover")
    workspace = _workspace(owner, "Primary")

    src_team = _team(workspace, owner, "Source Team")  # mover is NOT a member
    src_column = _column(workspace, src_team, owner, "Src")
    task = _task(workspace, src_team, owner, src_column)

    dest_team = _team(workspace, owner, "Dest Team", members=[mover])
    dest_column = _column(workspace, dest_team, owner, "Dest")

    client = APIClient()
    client.force_authenticate(user=mover)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": dest_column.pk}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    task.refresh_from_db()
    assert task.team_id == src_team.id  # unchanged
    assert task.column_id == src_column.id


def test_move_rejects_archived_trashed_task():
    # A task sitting in the recycle bin (ARCHIVED) must not be reassigned under
    # a live tombstone — moving it is a 400 with a clear message.
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")

    src_team = _team(workspace, owner, "Source Team")
    src_column = _column(workspace, src_team, owner, "Src")
    task = _task(workspace, src_team, owner, src_column)
    task.status = Task.ARCHIVED
    task.save(update_fields=["status"])

    dest_team = _team(workspace, owner, "Dest Team")
    dest_column = _column(workspace, dest_team, owner, "Dest")

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-move-board", kwargs={"task_id": task.pk})
    response = client.post(url, {"column": dest_column.pk}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    task.refresh_from_db()
    assert task.team_id == src_team.id  # unchanged
    assert task.status == Task.ARCHIVED

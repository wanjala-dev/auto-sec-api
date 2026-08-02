"""Integration: DELETE /api/v1/project/tasks/<task_id>/ → recycle bin.

Deleting a board card (a Task) must SOFT-DELETE it into the recycle bin, not
hard-delete it. These tests prove:

* the task is soft-deleted (``status=ARCHIVED``) — the row still exists, so it
  is NOT hard-deleted;
* it drops off the active board list query;
* it surfaces as a recycle-bin tombstone (entry_type='task');
* it is restorable via the existing recycle-bin restore flow (status returns);
* permission is enforced — a non-member outsider gets 403 and the task stays.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from components.project.infrastructure.repositories.project_repository import ProjectRepository
from components.recycle_bin.application.providers.recycle_bin_provider import (
    get_recycle_bin_service,
)
from components.recycle_bin.domain.enums import DeletionStage
from infrastructure.persistence.project.models import Column, Task
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
    return Workspace.objects.create(
        workspace_name=name,
        workspace_owner=owner,
        status="active",
    )


def _team(workspace, owner, title, members=()):
    team = Team.objects.create(workspace=workspace, title=title, created_by=owner)
    team.members.add(owner, *members)
    return team


def _column(workspace, team, owner, title="To Do"):
    return Column.objects.create(workspace=workspace, team=team, title=title, created_by=owner)


def _task(workspace, team, owner, column=None, title="QA Task", status_value=Task.TODO):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        column=column,
        title=title,
        status=status_value,
        created_by=owner,
    )


def test_delete_soft_deletes_task_into_recycle_bin_and_is_restorable():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team A")
    column = _column(workspace, team, owner)
    task = _task(workspace, team, owner, column, title="Alpha", status_value=Task.DONE)

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-update-by-id", kwargs={"task_id": task.pk})
    response = client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT

    # NOT hard-deleted — the row still exists, flagged ARCHIVED.
    task.refresh_from_db()
    assert Task.objects.filter(pk=task.pk).exists()
    assert task.status == Task.ARCHIVED

    # Excluded from the active board list query.
    listed = ProjectRepository().list_tasks_for_team_and_workspace(str(team.id), str(workspace.id))
    assert task.pk not in {t.pk for t in listed}

    # Present as a recycle-bin tombstone (entity_type='task', TRASHED).
    service = get_recycle_bin_service()
    entries = service.list_bin(workspace_id=workspace.id, entity_type="task")
    matching = [e for e in entries if e.entity_id == str(task.pk)]
    assert len(matching) == 1
    entry = matching[0]
    assert entry.stage == DeletionStage.TRASHED

    # Restorable via the existing recycle-bin restore flow — status returns.
    from components.recycle_bin.application.commands.restore_command import RestoreCommand

    service.restore(RestoreCommand(entry_id=entry.id, restored_by=owner.id))
    task.refresh_from_db()
    assert task.status == Task.DONE


def test_delete_is_idempotent_for_already_trashed_task():
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team A")
    task = _task(workspace, team, owner, title="Beta")

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-update-by-id", kwargs={"task_id": task.pk})

    first = client.delete(url)
    second = client.delete(url)

    assert first.status_code == status.HTTP_204_NO_CONTENT
    assert second.status_code == status.HTTP_204_NO_CONTENT
    assert Task.objects.filter(pk=task.pk).exists()


def test_delete_requires_permission_non_member_gets_403():
    owner = _user("owner")
    outsider = _user("outsider")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team A")
    task = _task(workspace, team, owner, title="Gamma")

    client = APIClient()
    client.force_authenticate(user=outsider)
    url = reverse("project:task-update-by-id", kwargs={"task_id": task.pk})
    response = client.delete(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    # Not trashed — the task is untouched.
    task.refresh_from_db()
    assert task.status == Task.TODO
    assert not get_recycle_bin_service().list_bin(workspace_id=workspace.id, entity_type="task")


def test_delete_missing_task_returns_404():
    owner = _user("owner")
    _workspace(owner, "Primary")

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("project:task-update-by-id", kwargs={"task_id": 999999})
    response = client.delete(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_from_different_workspace_is_forbidden_and_leaves_task_untouched():
    """Cross-workspace IDOR guard: a member of workspace B cannot delete a task
    in workspace A. Explicitly locks the isolation guarantee at the route."""
    owner_a = _user("owner_a")
    workspace_a = _workspace(owner_a, "Workspace A")
    team_a = _team(workspace_a, owner_a, "Team A")
    task = _task(workspace_a, team_a, owner_a, title="A's task")

    # ``attacker`` is a legitimate member of a DIFFERENT workspace.
    owner_b = _user("owner_b")
    workspace_b = _workspace(owner_b, "Workspace B")
    attacker = _user("attacker")
    _team(workspace_b, owner_b, "Team B", members=[attacker])

    client = APIClient()
    client.force_authenticate(user=attacker)
    url = reverse("project:task-update-by-id", kwargs={"task_id": task.pk})
    response = client.delete(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    task.refresh_from_db()
    assert task.status == Task.TODO  # untouched
    assert not get_recycle_bin_service().list_bin(workspace_id=workspace_a.id, entity_type="task")


def test_delete_verb_not_accepted_on_base_task_detail_route():
    """The soft-delete DELETE handler lives on ``TaskUpdateView`` only, so the
    base ``TaskDetailView`` routes must NOT accept DELETE (405) — a regression
    guard proving the delete verb didn't leak onto unrelated task routes."""
    owner = _user("owner")
    workspace = _workspace(owner, "Primary")
    team = _team(workspace, owner, "Team A")
    project = _project_for(workspace, team, owner)
    task = _task(workspace, team, owner, title="Delta")

    client = APIClient()
    client.force_authenticate(user=owner)
    # Base TaskDetailView route (name "user-tasks"): task/<project_id>/<uuid>/<task_id>
    url = reverse(
        "project:user-tasks",
        kwargs={"project_id": project.pk, "uuid": str(owner.id), "task_id": task.pk},
    )
    response = client.delete(url)

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    # The task was NOT trashed.
    task.refresh_from_db()
    assert task.status == Task.TODO


def _project_for(workspace, team, owner):
    from infrastructure.persistence.project.models import Project

    return Project.objects.create(workspace=workspace, team=team, title="P", created_by=owner)

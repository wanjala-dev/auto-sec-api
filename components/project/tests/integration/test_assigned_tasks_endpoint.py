"""Integration test: GET /api/v1/project/tasks/assigned-to-me/<workspace_id>/.

The "My Work" surface lists the tasks assigned to the current user in ONE
workspace, ACROSS ALL TEAMS. These tests prove the endpoint:

* returns every task assigned to the caller across different teams in the
  workspace;
* excludes tasks assigned to someone else, tasks in another workspace, and
  soft-deleted (ARCHIVED) tasks;
* returns the ``ProjectsView`` envelope so the frontend unwraps the list
  from ``response.data.data``;
* requires workspace membership.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from infrastructure.persistence.project.models import Task
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


def _team(workspace, owner, title, members):
    team = Team.objects.create(
        workspace=workspace,
        title=title,
        created_by=owner,
    )
    team.members.add(owner, *members)
    return team


def _task(workspace, team, creator, title, assignees, status_value=Task.TODO):
    task = Task.objects.create(
        workspace=workspace,
        team=team,
        created_by=creator,
        title=title,
        status=status_value,
    )
    if assignees:
        task.assigned_to.add(*assignees)
    return task


def test_returns_assigned_tasks_across_all_teams_and_excludes_the_rest():
    owner = _user("owner")
    member = _user("member")
    other = _user("other")

    workspace = _workspace(owner, "Primary")
    team_a = _team(workspace, owner, "Team A", [member, other])
    team_b = _team(workspace, owner, "Team B", [member])

    # Assigned to the caller, in two DIFFERENT teams -> both returned.
    task_a = _task(workspace, team_a, owner, "Task in Team A", [member])
    task_b = _task(workspace, team_b, owner, "Task in Team B", [member])

    # Excluded: assigned to someone else.
    _task(workspace, team_a, owner, "Someone else task", [other])
    # Excluded: soft-deleted (archived) even though assigned to the caller.
    _task(
        workspace,
        team_a,
        owner,
        "Archived task",
        [member],
        status_value=Task.ARCHIVED,
    )

    # Excluded: assigned to the caller but in a DIFFERENT workspace.
    owner2 = _user("owner2")
    other_ws = _workspace(owner2, "Other")
    team_c = _team(other_ws, owner2, "Team C", [member])
    _task(other_ws, team_c, owner2, "Other-workspace task", [member])

    client = APIClient()
    client.force_authenticate(user=member)
    url = reverse("project:tasks-assigned-to-me", kwargs={"workspace_id": workspace.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    body = response.data
    assert body["success"] is True
    returned_pks = {row["pk"] for row in body["data"]}
    assert returned_pks == {task_a.pk, task_b.pk}


def test_requires_workspace_membership():
    owner = _user("owner")
    outsider = _user("outsider")
    workspace = _workspace(owner, "Primary")

    client = APIClient()
    client.force_authenticate(user=outsider)
    url = reverse("project:tasks-assigned-to-me", kwargs={"workspace_id": workspace.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN

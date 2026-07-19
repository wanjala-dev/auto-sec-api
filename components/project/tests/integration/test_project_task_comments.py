import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from infrastructure.persistence.project.models import Project, Task, TaskComment
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import SubCategory, Workspace, WorkspaceCategory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    user = CustomUser.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="owner-pass",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def member():
    user = CustomUser.objects.create_user(
        username="member",
        email="member@example.com",
        password="member-pass",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def workspace(owner):
    category = WorkspaceCategory.objects.create(name="Education")
    subcategory = SubCategory.objects.create(name="STEM", category=category)
    workspace = Workspace.objects.create(workspace_name="Test Workspace", workspace_owner=owner)
    workspace.workspace_subcategories.add(subcategory)
    return workspace


@pytest.fixture
def team(workspace, owner):
    team = Team.objects.create(
        workspace=workspace,
        title="Team Alpha",
        created_by=owner,
    )
    team.members.add(owner)
    return team


@pytest.fixture
def project(workspace, team, owner):
    return Project.objects.create(
        workspace=workspace,
        team=team,
        title="Project Atlas",
        created_by=owner,
    )


@pytest.fixture
def task(workspace, team, project, owner):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        project=project,
        title="Design wireframes",
        created_by=owner,
    )


def test_member_can_create_root_comment(member, team, task):
    """Ensure task comment endpoints support discussion threads."""
    # Commenting requires workspace membership; team membership confers it.
    team.members.add(member)
    client = APIClient()
    client.force_authenticate(user=member)
    payload = {"comment": "Let us sync on requirements."}
    list_url = reverse("project:task-comments", kwargs={"task_id": task.id})

    response = client.post(list_url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert TaskComment.objects.count() == 1
    comment = TaskComment.objects.first()
    assert comment.comment == payload["comment"]
    assert comment.parent is None
    assert comment.task == task


def test_member_can_reply_to_existing_comment(member, team, task):
    """Test replying to an existing comment."""
    # Commenting requires workspace membership; team membership confers it.
    team.members.add(member)
    client = APIClient()
    parent = TaskComment.objects.create(
        comment="Initial idea",
        author=member,
        task=task,
    )

    client.force_authenticate(user=member)
    payload = {"comment": "Replying with more detail.", "parent": parent.id}
    list_url = reverse("project:task-comments", kwargs={"task_id": task.id})

    response = client.post(list_url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    reply = TaskComment.objects.exclude(id=parent.id).first()
    assert reply is not None
    assert reply.parent_id == parent.id


def test_list_endpoint_returns_nested_children(member, team, task):
    """Test that list endpoint returns nested children."""
    # Listing comments requires workspace membership; team membership confers it.
    team.members.add(member)
    client = APIClient()
    parent = TaskComment.objects.create(
        comment="Root comment",
        author=member,
        task=task,
    )
    TaskComment.objects.create(
        comment="Nested reply",
        author=member,
        task=task,
        parent=parent,
    )

    client.force_authenticate(user=member)
    list_url = reverse("project:task-comments", kwargs={"task_id": task.id})
    response = client.get(list_url)

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 1
    assert response.data[0]["id"] == parent.id
    assert len(response.data[0]["recipients"]) == 1

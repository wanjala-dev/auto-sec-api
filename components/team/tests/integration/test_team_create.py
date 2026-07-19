import pytest
from rest_framework.test import APIClient

from infrastructure.persistence.project.models import Column
from infrastructure.persistence.team.models import Team, TeamMembership
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


def _create_user(email: str, username: str) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password="pass1234",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _create_workspace(owner: CustomUser) -> Workspace:
    return Workspace.objects.create(
        workspace_name="Team Create Workspace",
        workspace_owner=owner,
        status="active",
    )



@pytest.mark.django_db
def test_team_create_endpoint_bootstraps_membership_and_columns():
    owner = _create_user("owner-create@example.com", "owner-create")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        "/team/",
        {
            "title": "Alpha",
            "plan": plan.id,
            "workspace": str(workspace.id),
        },
        format="json",
    )

    assert response.status_code == 201
    team = Team.objects.get(title="Alpha", created_by=owner)
    profile = UserProfile.objects.get(user=owner)

    assert response.json()["id"] == team.id
    assert team.members.filter(id=owner.id).exists()
    assert WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=owner,
        status=WorkspaceMembership.Status.ACTIVE,
    ).exists()
    assert TeamMembership.objects.filter(
        team=team,
        user=owner,
        status=TeamMembership.Status.ACTIVE,
    ).exists()
    assert profile.active_team_id == team.id
    assert profile.active_workspace_id == workspace.id
    assert Column.objects.filter(team=team, workspace=workspace, title="Backlog", order=1).exists()
    assert Column.objects.filter(team=team, workspace=workspace, title="Done", order=7).exists()


@pytest.mark.django_db
def test_team_create_endpoint_rejects_duplicate_title_for_creator():
    owner = _create_user("owner-duplicate@example.com", "owner-duplicate")
    workspace = _create_workspace(owner)
    Team.objects.create(title="Alpha", created_by=owner, workspace=workspace)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        "/team/",
        {
            "title": "Alpha",
            "plan": plan.id,
            "workspace": str(workspace.id),
        },
        format="json",
    )

    # Duplicate title is a conflict (409), surfaced through the shared domain
    # error handler as {"error", "error_code"}.
    assert response.status_code == 409
    assert response.json()["error"] == "A team with the same name already exists!"

import pytest
from rest_framework.test import APIClient

from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace


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
        workspace_name="Team Query Workspace",
        workspace_owner=owner,
        status="active",
    )



@pytest.mark.django_db
def test_workspace_team_list_excludes_teams_for_non_member():
    """Non-privileged viewers only see teams they belong to. An outsider with
    no team membership gets a 200 with an empty list — deliberately, to avoid
    the misleading UX of showing a team they'd be denied on open (only
    owners/admins/staff see every team in the workspace)."""
    owner = _create_user("owner-query@example.com", "owner-query")
    outsider = _create_user("outsider-query@example.com", "outsider-query")
    workspace = _create_workspace(owner)
    Team.objects.create(workspace=workspace, title="Alpha", created_by=owner)

    client = APIClient()
    client.force_authenticate(user=outsider)
    response = client.get(f"/team/workspaces/{workspace.id}/teams/")

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.django_db
def test_team_detail_returns_full_payload_for_member():
    owner = _create_user("owner-detail@example.com", "owner-detail")
    workspace = _create_workspace(owner)
    team = Team.objects.create(workspace=workspace, title="Bravo", created_by=owner)
    team.members.add(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get(f"/team/{team.id}/team")

    assert response.status_code == 200
    team_payload = response.json()["data"]
    assert "members" in team_payload
    assert team_payload["id"] == team.id


@pytest.mark.django_db
def test_team_add_view_lists_current_user_active_teams():
    owner = _create_user("owner-list@example.com", "owner-list")
    workspace = _create_workspace(owner)
    active_team = Team.objects.create(workspace=workspace, title="Current", created_by=owner)
    active_team.members.add(owner)
    Team.objects.create(workspace=workspace, title="Inactive", created_by=owner, status=Team.DELETED)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get("/team/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert [team["title"] for team in payload["data"]] == ["Current"]


@pytest.mark.django_db
def test_team_add_view_rejects_other_user_team_list():
    owner = _create_user("owner-self@example.com", "owner-self")
    other = _create_user("other-self@example.com", "other-self")

    client = APIClient()
    client.force_authenticate(user=other)
    response = client.get(f"/team/{owner.id}/")

    assert response.status_code == 403
    assert response.json()["error"] == "You do not have permission to access this resource."

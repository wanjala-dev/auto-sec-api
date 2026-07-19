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
        workspace_name="Team Update Workspace",
        workspace_owner=owner,
        status="active",
    )



@pytest.mark.django_db
def test_team_update_endpoint_updates_active_team_fields():
    owner = _create_user("owner-update@example.com", "owner-update")
    workspace = _create_workspace(owner)
    team = Team.objects.create(workspace=workspace, title="Alpha", created_by=owner)
    team.members.add(owner)
    profile = owner.profile
    profile.active_team_id = team.id
    profile.active_workspace_id = workspace.id
    profile.save(update_fields=["active_team_id", "active_workspace_id"])

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.patch(
        "/team/",
        {
            "title": "Renamed Team",
            "privacy": Team.PUBLIC,
        },
        format="json",
    )

    assert response.status_code == 200
    team.refresh_from_db()
    assert team.title == "Renamed Team"
    assert team.privacy == Team.PUBLIC
    assert response.json()["status"] == "success"
    assert response.json()["data"]["title"] == "Renamed Team"


@pytest.mark.django_db
def test_team_update_endpoint_requires_team_membership():
    owner = _create_user("owner-update-member@example.com", "owner-update-member")
    outsider = _create_user("outsider-update@example.com", "outsider-update")
    workspace = _create_workspace(owner)
    team = Team.objects.create(workspace=workspace, title="Alpha", created_by=owner)
    team.members.add(owner)
    profile = outsider.profile
    profile.active_team_id = team.id
    profile.active_workspace_id = workspace.id
    profile.save(update_fields=["active_team_id", "active_workspace_id"])

    client = APIClient()
    client.force_authenticate(user=outsider)
    response = client.patch(
        "/team/",
        {
            "title": "Renamed Team",
        },
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"] == "You must be a member of this team."

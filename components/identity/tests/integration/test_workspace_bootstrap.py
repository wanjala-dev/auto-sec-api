"""Coverage for user workspace bootstrap and identifier validation."""

import pytest
from django.urls import reverse

from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def test_list_workspaces_rejects_non_uuid_identifier(api_client):
    response = api_client.get("/identity/workspaces/1/")

    assert response.status_code == 400
    assert response.data["detail"] == "Invalid user id. Must be a valid UUID."


def test_list_workspaces_bootstraps_missing_workspace_for_authenticated_owner(api_client, user_factory):
    user = user_factory()
    user.is_onboard_complete = True
    user.save(update_fields=["is_onboard_complete"])

    api_client.force_authenticate(user=user)
    response = api_client.get(f"/identity/workspaces/{user.id}/")

    assert response.status_code == 200
    assert len(response.data["data"]) == 1

    workspace = Workspace.objects.get(workspace_owner=user)
    profile = UserProfile.objects.get(user=user)
    assert profile.active_workspace_id == workspace.id
    assert profile.active_team_id > 0


def test_user_patch_onboarding_bootstraps_workspace(api_client, user_factory):
    user = user_factory()
    api_client.force_authenticate(user=user)

    response = api_client.patch(
        reverse("user-base-edit", kwargs={"uuid": str(user.id)}),
        {"is_onboard_complete": True},
        format="json",
    )

    assert response.status_code == 200
    workspace = Workspace.objects.get(workspace_owner=user)
    profile = UserProfile.objects.get(user=user)
    assert profile.active_workspace_id == workspace.id

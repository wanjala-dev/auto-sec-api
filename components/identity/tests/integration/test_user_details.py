"""Coverage for the legacy user detail payload."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_user_details_returns_expected_payload(api_client, user_factory, workspace_factory, team_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    team = team_factory(workspace=workspace, created_by=user, members=[user])

    # This endpoint is self-or-staff (it returns email/names/workspaces);
    # authenticate as the subject so we exercise the legitimate self read.
    # The unauthenticated / cross-user deny is pinned in test_user_object_authz.
    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("legacy-user-detail", kwargs={"id": str(user.id)}))

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["user"]["id"] == str(user.id)
    assert any(item["id"] == team.id for item in payload["teams"])
    assert any(item["id"] == str(workspace.id) for item in payload["workspaces"])

"""Tests for workspace preference endpoints."""

import pytest

from infrastructure.persistence.notifications.userpreferences.models import (
    FINANCIAL_REPORT_FREQUENCY_KEY,
    FINANCIAL_REPORT_FREQUENCY_MONTHLY,
    WorkspacePreference,
)

pytestmark = pytest.mark.django_db


def test_workspace_preferences_get_creates_default(api_client, workspace_factory):
    """GET should create missing workspace preferences with defaults.

    Authenticates as the owner. This test used to call the endpoint
    ANONYMOUSLY and assert 200 — it was pinning the tenant-isolation hole
    (``IsUnauthenticatedOrAdminOrStaff`` let every safe method through for
    anyone) rather than the create-on-read behaviour it is named for. The
    behaviour under test is unchanged; only the caller is now a legitimate
    one. See ``test_workspace_settings_surface_authz.py``.
    """
    workspace = workspace_factory()

    api_client.force_authenticate(user=workspace.workspace_owner)
    response = api_client.get(f"/workspaces/{workspace.id}/preferences/")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["workspace"] == str(workspace.id)
    assert payload["financial_report_frequency"] == FINANCIAL_REPORT_FREQUENCY_MONTHLY
    assert WorkspacePreference.objects.filter(workspace=workspace).exists()


def test_workspace_preferences_patch_creates_and_updates(api_client, workspace_factory):
    """PATCH should create preferences on demand and update report frequency."""
    workspace = workspace_factory()

    api_client.force_authenticate(user=workspace.workspace_owner)
    response = api_client.patch(
        f"/workspaces/{workspace.id}/preferences/",
        {"financial_report_frequency": "weekly"},
        format="json",
    )

    assert response.status_code == 200, response.data
    preference = WorkspacePreference.objects.get(workspace=workspace)
    assert preference.get_settings()[FINANCIAL_REPORT_FREQUENCY_KEY] == "weekly"

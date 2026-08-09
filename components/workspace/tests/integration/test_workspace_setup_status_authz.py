"""Authorization guard for the setup-status endpoint.

GET /workspaces/<id>/setup-status/ names the workspace and describes its
security posture funnel (cloud connected? first scan run? Slack wired?) —
recon-grade data on a security product. It was readable unauthenticated and
cross-tenant (permission class returned True for every safe method + an
unfiltered workspace queryset). These tests lock the member-only floor, in
the spirit of the cross-tenant isolation locked for the finding read
surfaces (a3644c9).
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

pytestmark = [pytest.mark.django_db]


def _url(workspace) -> str:
    return reverse("workspace-setup-status", kwargs={"workspace": workspace.id})


class TestWorkspaceSetupStatusAuthz:
    def test_anonymous_is_refused(self, api_client, workspace_factory):
        workspace = workspace_factory()
        response = api_client.get(_url(workspace))
        assert response.status_code in (401, 403)

    def test_non_member_is_refused(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        outsider = user_factory()
        api_client.force_authenticate(user=outsider)
        response = api_client.get(_url(workspace))
        assert response.status_code == 403

    def test_owner_reads_their_own_funnel(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(user=workspace.workspace_owner)
        response = api_client.get(_url(workspace))
        assert response.status_code == 200
        assert response.data["data"]["workspace"] == str(workspace.id)

    def test_active_member_reads_the_funnel(self, api_client, workspace_factory, user_factory):
        workspace = workspace_factory()
        member = user_factory()
        WorkspaceMembership = django_apps.get_model("workspaces", "WorkspaceMembership")
        WorkspaceMembership.objects.create(workspace=workspace, user=member, role="viewer", status="active")
        api_client.force_authenticate(user=member)
        response = api_client.get(_url(workspace))
        assert response.status_code == 200

"""View-level test for the ATT&CK coverage endpoint.

Exercises ``AttckCoverageView`` through a real (authenticated) request — the layer
my earlier tests skipped (they called the use case directly), which is exactly why a
missing ``from django.utils import timezone`` import in the view shipped a 500. This
test would have caught it: it renders the response and asserts 200 + the shape.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from components.findings.api.controller import AttckCoverageView

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_attck_coverage_endpoint_returns_200_and_shape(workspace_factory, user_factory):
    ws = workspace_factory()
    user = user_factory()
    # staff bypasses the workspace-membership gate (is_workspace_member)
    user.is_staff = True
    user.save(update_fields=["is_staff"])

    request = APIRequestFactory().get(f"/findings/workspaces/{ws.id}/attack-coverage/")
    force_authenticate(request, user=user)

    # CELERY_TASK_ALWAYS_EAGER=True in test settings → the lazy recompute runs inline.
    response = AttckCoverageView.as_view()(request, workspace_id=str(ws.id))
    response.render()

    assert response.status_code == 200
    body = response.data
    assert body["success"] is True
    assert "coverage" in body["data"]
    assert "tactics" in body["data"]["coverage"]
    assert "refreshing" in body["data"]


def test_attck_coverage_endpoint_forbids_non_member(workspace_factory, user_factory):
    ws = workspace_factory()
    outsider = user_factory()  # not staff, not a member

    request = APIRequestFactory().get(f"/findings/workspaces/{ws.id}/attack-coverage/")
    force_authenticate(request, user=outsider)
    response = AttckCoverageView.as_view()(request, workspace_id=str(ws.id))

    assert response.status_code == 403

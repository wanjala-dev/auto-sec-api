"""Regression: POST /project/columns/ must accept TEAM-BOARD columns (project=None).

The conditional ``UniqueConstraint`` on ``Column``
(``uniq_board_column_title_per_team``, condition ``project__isnull=True``) makes
DRF auto-generate a ``UniqueTogetherValidator`` whose condition field
(``project``) is force-required unless the serializer field carries a default.
Before the fix, every team-board add-column from the HUD was rejected —
"project: This field is required." when omitted, "may not be null." when null —
caught live by the tests/qa kanban smoke (2026-08-08).

Covers: omitted project → 201; explicit null project → 201; project-board
column still works; and the duplicate-title guard on a team board still fires.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from infrastructure.persistence.project.models import Column, Project

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_URL = reverse("project:columns")


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return workspace, owner, team


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _payload(workspace, owner, team, title, **extra):
    return {
        "team": team.id,
        "workspace": str(workspace.id),
        "created_by": str(owner.id),
        "title": title,
        "order": 0,
        **extra,
    }


class TestTeamBoardColumnCreate:
    def test_creates_team_board_column_without_project(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)

        response = _client(owner).post(_URL, _payload(workspace, owner, team, "Escalated"), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        column = Column.objects.get(team=team, title="Escalated")
        assert column.project_id is None
        assert str(column.workspace_id) == str(workspace.id)

    def test_creates_team_board_column_with_explicit_null_project(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)

        response = _client(owner).post(_URL, _payload(workspace, owner, team, "Backlog", project=None), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Column.objects.filter(team=team, title="Backlog", project__isnull=True).exists()

    def test_project_board_column_still_creates(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        project = Project.objects.create(workspace=workspace, team=team, title="Hunt", created_by=owner, lead=owner)

        response = _client(owner).post(
            _URL, _payload(workspace, owner, team, "Hypotheses", project=project.id), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Column.objects.filter(project=project, title="Hypotheses").exists()

    def test_duplicate_team_board_title_still_rejected(self, workspace_factory, team_factory):
        """The conditional unique guard the validator exists for keeps firing."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        Column.objects.create(team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner)

        response = _client(owner).post(_URL, _payload(workspace, owner, team, "Triage"), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Column.objects.filter(team=team, title="Triage", project__isnull=True).count() == 1

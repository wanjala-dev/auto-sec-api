"""Integration — system ``BoardView`` rows are minted at RUNTIME (ADR 0030 §2).

Migration 0008 minted the system views for every team/project that existed
when the P1 backfill ran. Nothing minted them afterwards, so every team and
project created since had a full ``WorkflowStatus`` vocabulary (the P1 sync
bridge seeds those lazily) and ZERO ``BoardView`` rows — and with
``feature.boards_as_views`` ON the views bar renders only when
``teamViews.length > 0`` while the classic Board select is hidden, so the
flag was a strict loss of function on any workspace created after the
backfill: the team board and every project board became unreachable.

This module pins the invariant the backfill established as a RUNTIME one:

* a new team has its unfiltered "Board" system view;
* a new project has its ``{"project": "<id>"}`` system view;
* both are idempotent (re-saving never duplicates or renumbers);
* trashing a project retires its system view, restoring brings it back;
* the views API serves them — the QA repro, end to end;
* the rows are bound to the team's own workspace (tenancy invariant).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from components.project.domain.system_board_views import (
    TEAM_BOARD_VIEW_SLUG,
    project_board_view_slug,
)
from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.project.models import BoardView, Project

pytestmark = pytest.mark.django_db

FLAG_KEY = "feature.boards_as_views"


@pytest.fixture
def board(workspace_factory, team_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return owner, workspace, team


def _project(workspace, team, owner, *, title="QA FF Project"):
    return Project.objects.create(workspace=workspace, team=team, title=title, created_by=owner)


def _system_views(team):
    return BoardView.objects.filter(team=team, workspace=team.workspace, is_system=True)


class TestTeamBoardView:
    def test_a_new_team_gets_its_unfiltered_system_board_view(self, board):
        _owner, workspace, team = board

        view = _system_views(team).filter(slug=TEAM_BOARD_VIEW_SLUG).first()
        assert view is not None, "a team created at runtime has no system 'Board' view"
        assert view.name == "Board"
        assert view.filter == {}
        assert view.group_by == "status"
        assert view.is_system is True
        assert view.created_by_id is None  # system views belong to the team, not a person
        assert view.workspace_id == workspace.id

    def test_re_saving_the_team_never_duplicates_the_view(self, board):
        _owner, _workspace, team = board

        team.title = f"{team.title} renamed"
        team.save()
        team.save(update_fields=["title"])

        assert _system_views(team).filter(slug=TEAM_BOARD_VIEW_SLUG).count() == 1


class TestProjectBoardView:
    def test_a_new_project_gets_its_project_filtered_system_view(self, board):
        owner, workspace, team = board
        project = _project(workspace, team, owner)

        view = _system_views(team).filter(slug=project_board_view_slug(project.id)).first()
        assert view is not None, "a project created at runtime has no system view"
        assert view.name == "QA FF Project"
        assert view.filter == {"project": str(project.id)}
        assert view.is_system is True
        assert view.workspace_id == workspace.id
        # Ordered after the team board, which the ADR puts first.
        assert view.order > _system_views(team).get(slug=TEAM_BOARD_VIEW_SLUG).order

    def test_re_saving_the_project_never_duplicates_or_renumbers_the_view(self, board):
        owner, workspace, team = board
        project = _project(workspace, team, owner)
        slug = project_board_view_slug(project.id)
        first_order = _system_views(team).get(slug=slug).order

        project.title = "Renamed"
        project.save()

        assert _system_views(team).filter(slug=slug).count() == 1
        assert _system_views(team).get(slug=slug).order == first_order

    def test_trashing_a_project_retires_its_view_and_restoring_brings_it_back(self, board):
        owner, workspace, team = board
        project = _project(workspace, team, owner)
        slug = project_board_view_slug(project.id)

        project.is_deleted = True
        project.save(update_fields=["is_deleted"])
        assert not _system_views(team).filter(slug=slug).exists()

        project.is_deleted = False
        project.save(update_fields=["is_deleted"])
        assert _system_views(team).filter(slug=slug).count() == 1

    def test_two_projects_get_distinct_views(self, board):
        owner, workspace, team = board
        first = _project(workspace, team, owner, title="One")
        second = _project(workspace, team, owner, title="Two")

        slugs = set(_system_views(team).values_list("slug", flat=True))
        assert slugs == {
            TEAM_BOARD_VIEW_SLUG,
            project_board_view_slug(first.id),
            project_board_view_slug(second.id),
        }


class TestIsolation:
    def test_a_teams_system_views_never_land_in_another_workspace(self, workspace_factory, team_factory, user_factory):
        owner_a = user_factory()
        workspace_a = workspace_factory(owner=owner_a)
        team_a = team_factory(workspace=workspace_a, created_by=owner_a, members=[owner_a])
        owner_b = user_factory()
        workspace_b = workspace_factory(owner=owner_b)
        team_b = team_factory(workspace=workspace_b, created_by=owner_b, members=[owner_b])
        _project(workspace_a, team_a, owner_a)

        assert set(_system_views(team_a).values_list("workspace_id", flat=True)) == {workspace_a.id}
        assert set(_system_views(team_b).values_list("workspace_id", flat=True)) == {workspace_b.id}
        assert not BoardView.objects.filter(team=team_b, workspace=workspace_a).exists()


class TestViewsApiOnAFreshWorkspace:
    """The QA repro: brand-new workspace + flag ON must not be an empty bar."""

    @pytest.mark.real_feature_flags
    def test_the_views_endpoint_serves_the_team_board_and_the_project_board(self, api_client, board):
        owner, workspace, team = board
        project = _project(workspace, team, owner)
        flag, _ = FeatureFlag.objects.get_or_create(key=FLAG_KEY, defaults={"default_enabled": False})
        FeatureFlagRule.objects.create(
            flag=flag, scope=FeatureFlagRule.Scope.WORKSPACE, workspace=workspace, enabled=True
        )
        bump_feature_flags_version()

        api_client.force_authenticate(owner)
        response = api_client.get(reverse("project:team-board-views", kwargs={"team_id": team.id}))

        assert response.status_code == 200
        payload = response.data["data"]
        assert payload, "flag ON served an EMPTY views bar — the project board is unreachable"
        by_slug = {row["slug"]: row for row in payload}
        assert TEAM_BOARD_VIEW_SLUG in by_slug
        assert project_board_view_slug(project.id) in by_slug
        assert by_slug[project_board_view_slug(project.id)]["filter"] == {"project": str(project.id)}

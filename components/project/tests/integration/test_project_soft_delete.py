"""Integration — ProjectSoftDeleteAdapter round-trip.

Mirrors the recipient/budget adapter coverage. Asserts:
  1. soft_delete flips ``project.is_deleted`` True without removing the row and
     returns a snapshot the recycle bin can persist.
  2. restore flips it back so the project reappears.
  3. hard_delete removes the row (recycle-bin purge).
  4. The provider registry exposes 'project' so the recycle-bin controller
     accepts trash requests for projects.
  5. A soft-deleted project drops out of the board list queries.
"""
from __future__ import annotations

import pytest

from components.project.infrastructure.adapters.project_soft_delete_adapter import (
    ProjectSoftDeleteAdapter,
)
from components.project.infrastructure.repositories.project_repository import ProjectRepository
from components.recycle_bin.application.providers.recycle_bin_provider import (
    get_recycle_bin_service,
)
from infrastructure.persistence.project.models import Project

pytestmark = pytest.mark.django_db


def _project(workspace, team, user, *, title="QA Project"):
    return Project.objects.create(workspace=workspace, team=team, title=title, created_by=user)


class TestProjectSoftDeleteAdapter:
    def test_soft_delete_flips_flag_and_returns_snapshot(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        project = _project(workspace, team, owner, title="Alpha")

        snapshot = ProjectSoftDeleteAdapter().soft_delete(str(project.pk))

        project.refresh_from_db()
        assert project.is_deleted is True
        assert snapshot["id"] == str(project.pk)
        assert snapshot["title"] == "Alpha"
        assert snapshot["workspace_id"] == str(workspace.id)
        assert snapshot["team_id"] == str(team.id)

    def test_restore_reverts_flag(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        project = _project(workspace, team, owner)

        adapter = ProjectSoftDeleteAdapter()
        adapter.soft_delete(str(project.pk))
        project.refresh_from_db()
        assert project.is_deleted is True

        adapter.restore(str(project.pk))
        project.refresh_from_db()
        assert project.is_deleted is False

    def test_hard_delete_removes_row(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        project = _project(workspace, team, owner)
        pk = project.pk

        ProjectSoftDeleteAdapter().hard_delete(str(pk))

        assert not Project.objects.filter(pk=pk).exists()

    def test_provider_registry_includes_project(self) -> None:
        service = get_recycle_bin_service()
        assert "project" in service.provider.supported_types()


class TestSoftDeletedProjectsExcludedFromBoard:
    def test_list_for_workspace_and_team_skips_deleted(
        self, workspace_factory, team_factory, user_factory
    ) -> None:
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        team = team_factory(workspace=workspace, created_by=owner)
        kept = _project(workspace, team, owner, title="Kept")
        gone = _project(workspace, team, owner, title="Gone")

        ProjectSoftDeleteAdapter().soft_delete(str(gone.pk))

        ids = {
            p.pk
            for p in ProjectRepository().list_projects_for_workspace_and_team(
                str(workspace.id), str(team.id)
            )
        }
        assert kept.pk in ids
        assert gone.pk not in ids

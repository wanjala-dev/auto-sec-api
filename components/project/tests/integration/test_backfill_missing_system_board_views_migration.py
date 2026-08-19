"""Integration — the system-view repair (project migration 0011, ADR 0030 §2).

Migration 0008 minted the derived system views once; nothing minted them
afterwards, so every team and project created in the gap has none. The
runtime bridge fixes new rows; this migration is the one pass that can fix
rows already in the data, because a row created in the gap is never saved
again.

Follows the established migration-test pattern (0006/0008): call the
``RunPython`` function directly against real models. The runtime bridge now
creates these views whenever a test team/project is saved, so each scenario
STRIPS the ``BoardView`` rows after arranging its board — recreating the
exact pre-repair state the migration meets in production.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from components.project.domain.system_board_views import (
    TEAM_BOARD_VIEW_ORDER,
    TEAM_BOARD_VIEW_SLUG,
    project_board_view_slug,
)
from infrastructure.persistence.project.models import BoardView, Project

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_migration = importlib.import_module(
    "infrastructure.persistence.project.migrations.0011_backfill_missing_system_board_views"
)
backfill = _migration.backfill_missing_system_board_views


class _SchemaEditorStub:
    """The migration only reads ``schema_editor.connection.alias``."""

    class connection:
        alias = "default"


def _run_migration():
    backfill(django_apps, _SchemaEditorStub())


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return workspace, owner, team


def _strip_views(team):
    """Recreate the pre-repair state: the team exists, its views do not."""
    BoardView.objects.filter(team=team).delete()


class TestRepair:
    def test_a_team_created_in_the_gap_gets_its_board_view(self, workspace_factory, team_factory):
        workspace, _owner, team = _board(workspace_factory, team_factory)
        _strip_views(team)

        _run_migration()

        view = BoardView.objects.get(team=team, slug=TEAM_BOARD_VIEW_SLUG)
        assert view.is_system is True
        assert view.filter == {}
        assert view.order == TEAM_BOARD_VIEW_ORDER
        assert view.workspace_id == workspace.id

    def test_projects_created_in_the_gap_get_their_views(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        first = Project.objects.create(workspace=workspace, team=team, title="One", created_by=owner)
        second = Project.objects.create(workspace=workspace, team=team, title="Two", created_by=owner)
        _strip_views(team)

        _run_migration()

        slugs = set(BoardView.objects.filter(team=team).values_list("slug", flat=True))
        assert slugs == {
            TEAM_BOARD_VIEW_SLUG,
            project_board_view_slug(first.id),
            project_board_view_slug(second.id),
        }
        view = BoardView.objects.get(team=team, slug=project_board_view_slug(first.id))
        assert view.name == "One"
        assert view.filter == {"project": str(first.id)}

    def test_a_trashed_project_is_skipped(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        trashed = Project.objects.create(workspace=workspace, team=team, title="Gone", created_by=owner)
        trashed.is_deleted = True
        trashed.save(update_fields=["is_deleted"])
        _strip_views(team)

        _run_migration()

        assert not BoardView.objects.filter(team=team, slug=project_board_view_slug(trashed.id)).exists()

    def test_rerunning_is_a_no_op(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        Project.objects.create(workspace=workspace, team=team, title="One", created_by=owner)
        _strip_views(team)

        _run_migration()
        first_pass = dict(BoardView.objects.filter(team=team).values_list("slug", "order"))
        _run_migration()

        assert dict(BoardView.objects.filter(team=team).values_list("slug", "order")) == first_pass
        assert BoardView.objects.filter(team=team).count() == len(first_pass)

    def test_an_existing_personal_view_is_never_renumbered_or_touched(
        self, workspace_factory, team_factory, user_factory
    ):
        workspace, owner, team = _board(workspace_factory, team_factory)
        _strip_views(team)
        personal = BoardView.objects.create(
            workspace=workspace,
            team=team,
            name="My lens",
            slug="my-lens",
            filter={"min_severity": "high"},
            order=7,
            is_system=False,
            created_by=owner,
        )

        _run_migration()

        personal.refresh_from_db()
        assert personal.order == 7
        assert personal.is_system is False
        assert personal.created_by_id == owner.id
        # The repaired project views append AFTER the highest existing order.
        assert BoardView.objects.filter(team=team, slug=TEAM_BOARD_VIEW_SLUG).exists()

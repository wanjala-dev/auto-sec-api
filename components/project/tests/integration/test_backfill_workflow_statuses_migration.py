"""Integration tests for the P1 backfill (project migration 0008, ADR 0030).

Exercises ``backfill_workflow_statuses_and_board_views`` directly against real
models, following the established migration-test pattern (project migration
0006's tests): the six canonical statuses per team, the column-title mapping
(canonical 1:1, "Done" -> Complete, the AI vocabularies per the ADR's P3
table), the unknown-title exception path (team-local ``started`` status,
LOGGED), task backfill from columns, the system BoardView rows, re-runs are
no-ops — and the P1 "reads unchanged" pin: the backfill never creates,
renames, or deletes a Column.

The runtime sync bridge auto-creates statuses whenever a test column is
saved, so each scenario STRIPS the status rows after arranging its board —
recreating the exact pre-backfill state (columns and tasks exist, mirror
columns/tables empty) that the migration will meet in production.
"""

from __future__ import annotations

import importlib
import logging

import pytest
from django.apps import apps as django_apps

from infrastructure.persistence.project.models import (
    BoardView,
    Column,
    Project,
    Task,
    WorkflowStatus,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_migration = importlib.import_module(
    "infrastructure.persistence.project.migrations.0008_backfill_workflow_statuses_and_board_views"
)
backfill = _migration.backfill_workflow_statuses_and_board_views

CANONICAL_TITLES = ["Backlog", "Todo", "In Progress", "Testing", "Complete", "Canceled"]


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


def _column(workspace, owner, team, title, order, project=None):
    return Column.objects.create(
        team=team, workspace=workspace, project=project, title=title, order=order, created_by=owner
    )


def _strip_to_pre_backfill_state():
    """Delete every status/view the runtime bridge minted during arrange.

    ``WorkflowStatus`` deletion SET_NULLs ``Column.workflow_status`` and
    ``Task.workflow_status``, leaving exactly the pre-P1 shape the production
    migration will encounter.
    """
    WorkflowStatus.objects.all().delete()
    BoardView.objects.all().delete()


def test_creates_the_six_canonical_statuses_per_team(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    for order, title in enumerate(CANONICAL_TITLES, start=1):
        _column(workspace, owner, team, title, order)
    _strip_to_pre_backfill_state()

    _run_migration()

    statuses = list(WorkflowStatus.objects.filter(team=team, workspace=workspace).order_by("order"))
    assert [s.name for s in statuses] == CANONICAL_TITLES
    assert [s.category for s in statuses] == [
        "backlog",
        "unstarted",
        "started",
        "started",
        "completed",
        "canceled",
    ]


def test_canonical_columns_map_one_to_one(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    columns = {
        title: _column(workspace, owner, team, title, order) for order, title in enumerate(CANONICAL_TITLES, start=1)
    }
    _strip_to_pre_backfill_state()

    _run_migration()

    for title, column in columns.items():
        column.refresh_from_db()
        assert column.workflow_status is not None
        assert column.workflow_status.name == title


def test_legacy_done_column_maps_to_complete(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    done = _column(workspace, owner, team, "Done", 7)
    _strip_to_pre_backfill_state()

    _run_migration()

    done.refresh_from_db()
    assert done.workflow_status.name == "Complete"
    assert done.workflow_status.category == "completed"


def test_ai_columns_map_per_the_adr_p3_table(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    project = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
    expected = {
        # AI Findings project board
        "Suggested": ("Todo", "unstarted"),
        "Under Review": ("In Progress", "started"),
        "Accepted": ("Complete", "completed"),
        "Dismissed": ("Canceled", "canceled"),
        # Agents team-board lazy lanes
        "Triage": ("In Progress", "started"),
        "Optimize": ("In Progress", "started"),
    }
    project_titles = {"Suggested", "Under Review", "Accepted", "Dismissed"}
    columns = {
        title: _column(
            workspace,
            owner,
            team,
            title,
            order,
            project=project if title in project_titles else None,
        )
        for order, title in enumerate(expected, start=0)
    }
    _strip_to_pre_backfill_state()

    _run_migration()

    for title, (status_name, category) in expected.items():
        column = columns[title]
        column.refresh_from_db()
        assert column.workflow_status.name == status_name, title
        assert column.workflow_status.category == category, title


def test_unknown_title_creates_a_team_local_started_status_and_logs_it(workspace_factory, team_factory, caplog):
    workspace, owner, team = _board(workspace_factory, team_factory)
    rogue = _column(workspace, owner, team, "Security Review", 9)
    _strip_to_pre_backfill_state()

    with caplog.at_level(logging.WARNING):
        _run_migration()

    rogue.refresh_from_db()
    assert rogue.workflow_status.name == "Security Review"
    assert rogue.workflow_status.category == "started"
    assert rogue.workflow_status.order > 6, "team-local statuses land after the canonical set"
    assert any("workflow_status_backfill unmapped column" in record.message for record in caplog.records), (
        "the ADR's 'exceptions logged' must actually log"
    )


def test_tasks_inherit_their_column_status_and_columnless_tasks_stay_null(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    todo = _column(workspace, owner, team, "Todo", 2)
    carded = Task.objects.create(workspace=workspace, team=team, column=todo, title="carded", created_by=owner)
    floating = Task.objects.create(workspace=workspace, team=team, column=None, title="floating", created_by=owner)
    _strip_to_pre_backfill_state()

    _run_migration()

    carded.refresh_from_db()
    floating.refresh_from_db()
    todo.refresh_from_db()
    assert carded.workflow_status_id == todo.workflow_status_id
    assert carded.workflow_status_id is not None
    assert floating.workflow_status_id is None


def test_system_board_views_are_created(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    _column(workspace, owner, team, "Todo", 2)
    with_columns = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
    _column(workspace, owner, team, "Suggested", 0, project=with_columns)
    Project.objects.create(workspace=workspace, team=team, title="No Board", created_by=owner)
    _strip_to_pre_backfill_state()

    _run_migration()

    team_view = BoardView.objects.get(team=team, workspace=workspace, slug="board")
    assert team_view.name == "Board"
    assert team_view.filter == {}
    assert team_view.group_by == "status"
    assert team_view.is_system is True

    project_view = BoardView.objects.get(team=team, workspace=workspace, slug=f"project-{with_columns.id}")
    assert project_view.name == "AI Findings"
    assert project_view.filter == {"project": str(with_columns.id)}
    assert project_view.is_system is True

    assert BoardView.objects.filter(team=team).count() == 2, "a project with no columns gets no view"


def test_reads_are_untouched_no_column_is_created_renamed_or_deleted(workspace_factory, team_factory):
    """The P1 pin: Column stays authoritative and reads see NOTHING change."""
    workspace, owner, team = _board(workspace_factory, team_factory)
    for order, title in enumerate([*CANONICAL_TITLES, "Suggested", "Weird Lane"], start=1):
        _column(workspace, owner, team, title, order)
    _strip_to_pre_backfill_state()
    before = list(Column.objects.order_by("id").values("id", "title", "order", "project_id", "is_deleted"))

    _run_migration()

    after = list(Column.objects.order_by("id").values("id", "title", "order", "project_id", "is_deleted"))
    assert after == before


def test_migration_is_re_runnable(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    for order, title in enumerate([*CANONICAL_TITLES, "Weird Lane"], start=1):
        _column(workspace, owner, team, title, order)
    project = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
    suggested = _column(workspace, owner, team, "Suggested", 0, project=project)
    Task.objects.create(workspace=workspace, team=team, column=suggested, title="card", created_by=owner)
    _strip_to_pre_backfill_state()

    _run_migration()
    statuses_first = set(WorkflowStatus.objects.values_list("id", "name", "category", "order"))
    views_first = set(BoardView.objects.values_list("id", "slug", "is_system"))
    tasks_first = set(Task.objects.values_list("id", "workflow_status_id"))

    _run_migration()

    assert set(WorkflowStatus.objects.values_list("id", "name", "category", "order")) == statuses_first
    assert set(BoardView.objects.values_list("id", "slug", "is_system")) == views_first
    assert set(Task.objects.values_list("id", "workflow_status_id")) == tasks_first

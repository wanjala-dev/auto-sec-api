"""Integration tests for the Done→Complete merge (project migration 0006, F7).

Exercises ``merge_done_into_complete`` directly against real models, following
the established migration-test pattern
(``components/team/tests/integration/test_merge_default_teams_migration.py``):
an empty "Done" team-board lane is removed; a "Done" with cards merges them
into "Complete" appending after Complete's cards while preserving relative
order; a board with no "Complete" adopts the canonical name; AI-agents boards
are never touched; re-runs are no-ops.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from infrastructure.persistence.project.models import Column, Task
from infrastructure.persistence.team.models import Team

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_migration = importlib.import_module("infrastructure.persistence.project.migrations.0006_merge_done_into_complete")
merge_done_into_complete = _migration.merge_done_into_complete


class _SchemaEditorStub:
    """The migration only reads ``schema_editor.connection.alias``."""

    class connection:
        alias = "default"


def _run_migration():
    merge_done_into_complete(django_apps, _SchemaEditorStub())


def _board(workspace_factory, team_factory, *, team_kind: str | None = None):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    overrides = {"workspace": workspace, "created_by": owner, "members": [owner]}
    if team_kind is not None:
        overrides["kind"] = team_kind
    team = team_factory(**overrides)
    return workspace, owner, team


def _column(workspace, owner, team, title, order):
    return Column.objects.create(
        team=team, workspace=workspace, project=None, title=title, order=order, created_by=owner
    )


def _task(workspace, owner, team, column, title, order):
    return Task.objects.create(
        workspace=workspace, team=team, column=column, title=title, order=order, created_by=owner
    )


def test_empty_done_column_is_removed(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    _column(workspace, owner, team, "Complete", 5)
    done = _column(workspace, owner, team, "Done", 7)

    _run_migration()

    assert not Column.objects.filter(pk=done.pk).exists()
    assert Column.objects.filter(team=team, project__isnull=True, title="Complete").count() == 1


def test_done_cards_merge_into_complete_appended_in_order(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    complete = _column(workspace, owner, team, "Complete", 5)
    done = _column(workspace, owner, team, "Done", 7)
    _task(workspace, owner, team, complete, "already complete", 1)
    _task(workspace, owner, team, complete, "also complete", 2)
    # Done's cards deliberately carry non-contiguous orders — only their
    # RELATIVE order must survive the merge.
    done_b = _task(workspace, owner, team, done, "done second", 9)
    done_a = _task(workspace, owner, team, done, "done first", 5)

    _run_migration()

    assert not Column.objects.filter(pk=done.pk).exists()
    done_a.refresh_from_db()
    done_b.refresh_from_db()
    assert done_a.column_id == complete.pk
    assert done_b.column_id == complete.pk
    assert (done_a.order, done_b.order) == (3, 4), "merged cards append after Complete's max, in Done order"
    titles = list(Task.objects.filter(column=complete).order_by("order", "created_at").values_list("title", flat=True))
    assert titles == ["already complete", "also complete", "done first", "done second"]


def test_done_without_complete_adopts_the_canonical_name(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    done = _column(workspace, owner, team, "Done", 3)
    card = _task(workspace, owner, team, done, "keep me visible", 1)

    _run_migration()

    done.refresh_from_db()
    assert done.title == "Complete"
    card.refresh_from_db()
    assert card.column_id == done.pk, "no card may be orphaned by the rename"


def test_soft_deleted_complete_is_restored_for_the_merge(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    complete = _column(workspace, owner, team, "Complete", 5)
    complete.is_deleted = True
    complete.save(update_fields=["is_deleted"])
    done = _column(workspace, owner, team, "Done", 7)
    card = _task(workspace, owner, team, done, "live card", 1)

    _run_migration()

    complete.refresh_from_db()
    assert complete.is_deleted is False, "live cards must never merge into a hidden lane"
    card.refresh_from_db()
    assert card.column_id == complete.pk
    assert not Column.objects.filter(pk=done.pk).exists()


def test_ai_agents_boards_are_never_touched(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory, team_kind=Team.Kind.AI_AGENTS)
    done = _column(workspace, owner, team, "Done", 3)

    _run_migration()

    assert Column.objects.filter(pk=done.pk).exists(), "the agents context owns its board vocabulary"


def test_migration_is_idempotent(workspace_factory, team_factory):
    workspace, owner, team = _board(workspace_factory, team_factory)
    complete = _column(workspace, owner, team, "Complete", 5)
    done = _column(workspace, owner, team, "Done", 7)
    _task(workspace, owner, team, done, "one card", 1)

    _run_migration()
    _run_migration()  # second run finds no Done columns and no-ops

    assert Column.objects.filter(team=team, project__isnull=True, title="Complete").count() == 1
    assert Task.objects.filter(column=complete).count() == 1

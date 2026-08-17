"""``ensure_team_board_columns`` is APPEND-ONLY (QA report 2026-08-16, F3).

The seeder re-runs from several paths — team create, ``seed_security_teams``
(which iterates EVERY workspace), ``backfill_team_board_columns``, and the
agents kanban sync (F4). Before the fix it re-asserted the seed order on every
run, silently reverting operator column reorders — the one mechanism that
could make a board reorder appear not to stick.
"""

from __future__ import annotations

import pytest

from components.workspace.infrastructure.adapters.workspace_utils import (
    DEFAULT_BOARD_COLUMNS,
    ensure_team_board_columns,
)
from infrastructure.persistence.project.models import Column, Project

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return workspace, owner, team


def _titles_in_board_order(team) -> list[str]:
    return list(
        Column.objects.filter(team=team, project__isnull=True, is_deleted=False)
        .order_by("order", "id")
        .values_list("title", flat=True)
    )


class TestSeederAppendOnly:
    def test_fresh_board_gets_canonical_lanes_with_unique_orders(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)

        ensure_team_board_columns(workspace, team, owner)

        assert _titles_in_board_order(team) == [title for title, _ in DEFAULT_BOARD_COLUMNS]
        orders = list(Column.objects.filter(team=team, project__isnull=True).values_list("order", flat=True))
        assert len(orders) == len(set(orders)), "seeded orders must be collision-free"

    def test_rerun_preserves_operator_reorder(self, workspace_factory, team_factory):
        """THE F3 landmine: a seeder re-run must never revert a drag-reorder."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        ensure_team_board_columns(workspace, team, owner)

        # Operator drags "Todo" to the front — exactly what ColumnReorderView
        # persists (order values swapped, everything else untouched).
        todo = Column.objects.get(team=team, project__isnull=True, title="Todo")
        backlog = Column.objects.get(team=team, project__isnull=True, title="Backlog")
        todo.order, backlog.order = backlog.order, todo.order
        todo.save(update_fields=["order"])
        backlog.save(update_fields=["order"])
        reordered = _titles_in_board_order(team)
        assert reordered[0] == "Todo"

        ensure_team_board_columns(workspace, team, owner)  # any re-run path

        assert _titles_in_board_order(team) == reordered

    def test_missing_column_is_appended_after_current_max(self, workspace_factory, team_factory):
        workspace, owner, team = _board(workspace_factory, team_factory)
        ensure_team_board_columns(workspace, team, owner)
        Column.objects.get(team=team, project__isnull=True, title="Canceled").delete()
        # The operator also added a custom lane at the end of the board.
        Column.objects.create(team=team, workspace=workspace, project=None, title="QA", order=9, created_by=owner)

        ensure_team_board_columns(workspace, team, owner)

        canceled = Column.objects.get(team=team, project__isnull=True, title="Canceled")
        assert canceled.order == 10, "recreated column must append after the board max, not re-seed its old slot"

    def test_repairs_still_run_without_touching_order(self, workspace_factory, team_factory):
        """The dedupe / project=NULL / created_by repairs survive the F3 fix."""
        workspace, owner, team = _board(workspace_factory, team_factory)
        project = Project.objects.create(workspace=workspace, team=team, title="Hunt", created_by=owner, lead=owner)
        # Legacy shape: a seeded title stranded on a project, no creator.
        stray = Column.objects.create(
            team=team, workspace=workspace, project=project, title="Backlog", order=42, created_by=None
        )

        ensure_team_board_columns(workspace, team, owner)

        stray.refresh_from_db()
        assert stray.project_id is None, "project=NULL repair must still run"
        assert stray.created_by_id == owner.id, "created_by backfill must still run"
        assert stray.order == 42, "repairs must never rewrite an existing column's order"

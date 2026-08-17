"""``ensure_board_column`` order assignment (QA report 2026-08-16, F8).

The auto-created acting columns (Triage / Optimize) used ``first().order + 1``
— the board MINIMUM plus one — so on a default six-lane board every
auto-created column collided with an existing lane's order (Triage landing on
Todo's slot), and ``Column.Meta.ordering`` had no tiebreaker, so the board
layout was unstable. New columns must land AFTER every existing lane.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.tools._finding_processing import ensure_board_column
from components.workspace.infrastructure.adapters.workspace_utils import ensure_team_board_columns
from infrastructure.persistence.project.models import Column

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _default_board(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    ensure_team_board_columns(workspace, team, owner)  # Backlog(1) … Canceled(6)
    return workspace, owner, team


class TestEnsureBoardColumnOrder:
    def test_new_column_lands_after_every_existing_lane(self, workspace_factory, team_factory):
        workspace, owner, team = _default_board(workspace_factory, team_factory)

        triage = ensure_board_column(team, workspace, owner, "Triage")
        optimize = ensure_board_column(team, workspace, owner, "Optimize")

        assert triage.order == 7, "auto column must take max+1, not min+1 (the F8 collision)"
        assert optimize.order == 8
        orders = list(Column.objects.filter(team=team, project__isnull=True).values_list("order", flat=True))
        assert len(orders) == len(set(orders)), "no two board columns may share an order"

    def test_existing_column_is_returned_untouched(self, workspace_factory, team_factory):
        workspace, owner, team = _default_board(workspace_factory, team_factory)
        first = ensure_board_column(team, workspace, owner, "Triage")

        again = ensure_board_column(team, workspace, owner, "Triage")

        assert again.id == first.id
        assert again.order == first.order

    def test_empty_board_starts_at_one(self, workspace_factory, team_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])

        column = ensure_board_column(team, workspace, owner, "Triage")

        assert column.order == 1

    def test_equal_orders_break_ties_deterministically(self, workspace_factory, team_factory):
        """``Meta.ordering`` carries an ``id`` tiebreaker so a legacy collision
        still renders a stable board."""
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        first = Column.objects.create(
            team=team, workspace=workspace, project=None, title="A", order=5, created_by=owner
        )
        second = Column.objects.create(
            team=team, workspace=workspace, project=None, title="B", order=5, created_by=owner
        )

        assert list(Column.objects.filter(team=team).values_list("id", flat=True)) == [first.id, second.id]
        assert Column._meta.ordering == ["order", "id"]

"""The ensure path seeds the one-surface AI board (ADR 0030 P3).

``ensure_agents_board`` is the pipeline's provisioning choke point (workspace
bootstrap, every finding land, the ops backfill command). P3 pins:

* the "AI Findings" project board carries the CANONICAL six lanes — the same
  vocabulary as every other board; no AI-only lane titles remain;
* every lane carries its ``workflow_status`` (via the P1 sync bridge);
* the Agents team's "Intake"/"Acting" system views are seeded with the
  closed-vocabulary filters — this is what covers workspaces created AFTER
  the 0009 data migration ran;
* the whole thing is idempotent — a second call creates nothing;
* a lane soft-deleted (e.g. by a rollback exercise) is not silently adopted.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.services.agents_board_service import (
    CANCELED,
    COMPLETE,
    IN_PROGRESS,
    TODO,
    ensure_agents_board,
)
from components.project.domain.workflow_status_vocabulary import CANONICAL_STATUSES
from infrastructure.persistence.project.models import BoardView, Column

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

CANONICAL_TITLES = [name for name, _category, _order in CANONICAL_STATUSES]


class TestEnsureAgentsBoard:
    def test_seeds_the_canonical_six_lanes_on_the_project_board(self, workspace_factory):
        workspace = workspace_factory()

        board = ensure_agents_board(workspace)

        titles = sorted(board.columns_by_title)
        assert titles == sorted(CANONICAL_TITLES)
        for column in board.columns_by_title.values():
            assert column.project_id == board.project.id
            assert column.team_id == board.team.id
            assert column.workflow_status_id is not None  # P1 bridge mapped it
        # The lifecycle constants resolve against the seeded board.
        for title in (TODO, IN_PROGRESS, COMPLETE, CANCELED):
            assert board.column(title) is not None

    def test_seeds_the_intake_and_acting_system_views(self, workspace_factory):
        workspace = workspace_factory()

        board = ensure_agents_board(workspace)

        views = {v.slug: v for v in BoardView.objects.filter(team=board.team, workspace=workspace, is_system=True)}
        assert views["intake"].filter == {"source_type_prefix": "ai.", "category": "unstarted"}
        assert views["acting"].filter == {"source_type_prefix": "ai.", "category": "started"}

    def test_second_call_is_idempotent(self, workspace_factory):
        workspace = workspace_factory()

        first = ensure_agents_board(workspace)
        columns_before = Column.objects.filter(team=first.team, workspace=workspace).count()
        views_before = BoardView.objects.filter(team=first.team, workspace=workspace).count()

        second = ensure_agents_board(workspace)

        assert second.project.id == first.project.id
        assert Column.objects.filter(team=first.team, workspace=workspace).count() == columns_before
        assert BoardView.objects.filter(team=first.team, workspace=workspace).count() == views_before

    def test_soft_deleted_lane_is_not_adopted(self, workspace_factory):
        workspace = workspace_factory()
        board = ensure_agents_board(workspace)
        retired = board.column(TODO)
        retired.is_deleted = True
        retired.save(update_fields=["is_deleted"])

        healed = ensure_agents_board(workspace)

        assert healed.column(TODO).id != retired.id
        assert healed.column(TODO).is_deleted is False

"""Queries: boards-as-views reads (ADR 0030 P2a).

No Django imports — depends only on ports. Thin by design (mirrors
``column_query.py``): parameter clamping lives here, everything else is the
port's contract.
"""

from __future__ import annotations

from typing import Any

from components.workspace.application.ports.board_view_query_port import (
    BoardViewQueryPort,
    ViewBoard,
)
from components.workspace.application.ports.column_query_port import (
    ColumnTasksPage,
    clamp_tasks_limit,
)


class FetchTeamBoardViewsQuery:
    """Application query for a team's saved board views (the views bar)."""

    def __init__(self, query_port: BoardViewQueryPort) -> None:
        self._port = query_port

    def execute(self, *, team_id: Any, user: Any) -> list[Any]:
        return self._port.fetch_team_views(team_id=team_id, user=user)


class FetchViewBoardQuery:
    """Application query for one view's board (status lanes + windowed tasks)."""

    def __init__(self, query_port: BoardViewQueryPort) -> None:
        self._port = query_port

    def execute(self, *, view_id: Any, user: Any, tasks_limit: Any = None) -> ViewBoard:
        return self._port.fetch_view_board(
            view_id=view_id,
            user=user,
            tasks_limit=clamp_tasks_limit(tasks_limit),
        )


class FetchViewLaneTasksQuery:
    """Application query for one status lane's task window (board "load more")."""

    def __init__(self, query_port: BoardViewQueryPort) -> None:
        self._port = query_port

    def execute(
        self, *, view_id: Any, status_id: Any, user: Any, offset: Any = 0, limit: Any = None
    ) -> ColumnTasksPage:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0
        return self._port.fetch_view_lane_tasks(
            view_id=view_id,
            status_id=status_id,
            user=user,
            offset=max(0, offset),
            limit=clamp_tasks_limit(limit),
        )

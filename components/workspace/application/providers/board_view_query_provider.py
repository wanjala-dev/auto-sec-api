from __future__ import annotations

from components.workspace.application.queries.board_view_query import (
    FetchTeamBoardViewsQuery,
    FetchViewBoardQuery,
    FetchViewLaneTasksQuery,
)
from components.workspace.infrastructure.repositories.board_view_query_repository import (
    OrmBoardViewQueryRepository,
)


class BoardViewQueryProvider:
    """Composition root for the boards-as-views reads (ADR 0030 P2a)."""

    @staticmethod
    def build_team_views_query() -> FetchTeamBoardViewsQuery:
        return FetchTeamBoardViewsQuery(query_port=OrmBoardViewQueryRepository())

    @staticmethod
    def build_view_board_query() -> FetchViewBoardQuery:
        return FetchViewBoardQuery(query_port=OrmBoardViewQueryRepository())

    @staticmethod
    def build_view_lane_tasks_query() -> FetchViewLaneTasksQuery:
        return FetchViewLaneTasksQuery(query_port=OrmBoardViewQueryRepository())

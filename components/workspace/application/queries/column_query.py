"""Query: Fetch columns with filter parameters.

No Django imports — depends only on port.
"""

from __future__ import annotations

from typing import Any

from components.workspace.application.ports.column_query_port import (
    ColumnFilterRequest,
    ColumnQueryPort,
    ColumnTasksPage,
    clamp_tasks_limit,
)


class FetchColumnsQuery:
    """Application query for column listing."""

    def __init__(self, query_port: ColumnQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: ColumnFilterRequest) -> list[Any]:
        return self._port.fetch_columns(request=request)

    @staticmethod
    def parse_params(
        *,
        column_id: Any | None = None,
        project_id: Any | None = None,
        team_id: Any | None = None,
        workspace_id: Any | None = None,
        user_assigned: str | None = None,
        user: Any | None = None,
        tasks_limit: Any | None = None,
    ) -> ColumnFilterRequest:
        """Build a typed request from URL kwargs and query params."""
        return ColumnFilterRequest(
            column_id=column_id,
            project_id=project_id,
            team_id=team_id,
            workspace_id=workspace_id,
            user_assigned=bool(user_assigned),
            user=user,
            tasks_limit=clamp_tasks_limit(tasks_limit),
        )


class FetchColumnTasksQuery:
    """Application query for one lane's task window (board "load more")."""

    def __init__(self, query_port: ColumnQueryPort) -> None:
        self._port = query_port

    def execute(self, *, column_id: Any, user: Any, offset: Any = 0, limit: Any = None) -> ColumnTasksPage:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0
        return self._port.fetch_column_tasks(
            column_id=column_id,
            user=user,
            offset=max(0, offset),
            limit=clamp_tasks_limit(limit),
        )

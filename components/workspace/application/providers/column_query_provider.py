from __future__ import annotations

from components.workspace.application.queries.column_query import (
    FetchColumnsQuery,
    FetchColumnTasksQuery,
)
from components.workspace.infrastructure.repositories.column_query_repository import (
    OrmColumnQueryRepository,
)


class ColumnQueryProvider:
    @staticmethod
    def build_query() -> FetchColumnsQuery:
        return FetchColumnsQuery(query_port=OrmColumnQueryRepository())

    @staticmethod
    def build_column_tasks_query() -> FetchColumnTasksQuery:
        return FetchColumnTasksQuery(query_port=OrmColumnQueryRepository())

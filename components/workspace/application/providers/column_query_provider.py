from __future__ import annotations

from components.workspace.application.queries.column_query import FetchColumnsQuery
from components.workspace.infrastructure.repositories.column_query_repository import (
    OrmColumnQueryRepository,
)


class ColumnQueryProvider:
    @staticmethod
    def build_query() -> FetchColumnsQuery:
        return FetchColumnsQuery(query_port=OrmColumnQueryRepository())

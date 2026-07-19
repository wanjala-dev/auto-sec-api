from __future__ import annotations

from components.workspace.application.queries.workspace_detail_query import (
    FetchWorkspaceDetailQuery,
)
from components.workspace.infrastructure.repositories.workspace_detail_query_repository import (
    OrmWorkspaceDetailQueryRepository,
)


class WorkspaceDetailQueryProvider:
    @staticmethod
    def build_query() -> FetchWorkspaceDetailQuery:
        return FetchWorkspaceDetailQuery(
            query_port=OrmWorkspaceDetailQueryRepository(),
        )

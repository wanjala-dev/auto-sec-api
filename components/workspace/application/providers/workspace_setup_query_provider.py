from __future__ import annotations

from components.workspace.application.queries.workspace_setup_query import (
    WorkspaceSetupQueryService,
)
from components.workspace.domain.policies.workspace_setup_policy_service import (
    WorkspaceSetupPolicyService,
)
from components.workspace.infrastructure.repositories.workspace_setup_query_repository import (
    OrmWorkspaceSetupQueryRepository,
)


class WorkspaceSetupQueryProvider:
    def build_service(self) -> WorkspaceSetupQueryService:
        return WorkspaceSetupQueryService(
            workspace_setup_queries=OrmWorkspaceSetupQueryRepository(),
            workspace_setup_policy=WorkspaceSetupPolicyService(),
        )

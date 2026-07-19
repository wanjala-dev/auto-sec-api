from __future__ import annotations

from components.workspace.domain.policies.workspace_setup_policy_service import (
    SetupCheckResult,
    WorkspaceSetupPolicyService,
)
from components.workspace.application.ports.workspace_setup_query_port import (
    WorkspaceSetupQueryPort,
)


class WorkspaceSetupQueryService:
    def __init__(
        self,
        *,
        workspace_setup_queries: WorkspaceSetupQueryPort,
        workspace_setup_policy: WorkspaceSetupPolicyService,
    ) -> None:
        self.workspace_setup_queries = workspace_setup_queries
        self.workspace_setup_policy = workspace_setup_policy

    @property
    def definitions(self):
        return self.workspace_setup_policy.definitions

    def annotate_setup_state(self, queryset):
        return self.workspace_setup_queries.annotate_setup_state(queryset)

    def get_setup_results(self, workspace) -> list[SetupCheckResult]:
        snapshot = self.workspace_setup_queries.build_setup_snapshot(workspace)
        return self.workspace_setup_policy.evaluate(snapshot)

    def build_status(self, workspace) -> dict:
        snapshot = self.workspace_setup_queries.build_setup_snapshot(workspace)
        return self.workspace_setup_policy.build_status(snapshot)

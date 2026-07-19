from __future__ import annotations

from components.workspace.application.use_cases.bootstrap_workspace_content_use_case import (
    BootstrapWorkspaceContentUseCase,
)
from components.workspace.application.use_cases.bootstrap_workspace_from_config_use_case import (
    BootstrapWorkspaceFromConfigUseCase,
)
from components.workspace.application.use_cases.bootstrap_workspace_setup_use_case import (
    BootstrapWorkspaceSetupUseCase,
)
from components.workspace.application.use_cases.create_workspace_use_case import (
    CreateWorkspaceUseCase,
)
from components.workspace.application.use_cases.finalize_workspace_bootstrap_use_case import (
    FinalizeWorkspaceBootstrapUseCase,
)
from components.workspace.application.use_cases.seed_staff_accounts_use_case import (
    SeedStaffAccountsUseCase,
)
from components.workspace.infrastructure.adapters.management_command_workspace_bootstrap_feedback_adapter import (
    ManagementCommandWorkspaceBootstrapFeedbackAdapter,
)
from components.workspace.infrastructure.repositories.workspace_bootstrap_repository import (
    WorkspaceBootstrapRepository,
)
from components.workspace.infrastructure.repositories.workspace_staff_account_repository import (
    WorkspaceStaffAccountRepository,
)


class WorkspaceBootstrapProvider:
    """Application-level composition for workspace bootstrap flows."""

    @staticmethod
    def build_create_workspace_use_case() -> CreateWorkspaceUseCase:
        return CreateWorkspaceUseCase(
            bootstrap_port=WorkspaceBootstrapRepository(),
        )

    def build_use_case(self, *, command) -> BootstrapWorkspaceFromConfigUseCase:
        workspace_bootstrap_store = WorkspaceBootstrapRepository()
        return BootstrapWorkspaceFromConfigUseCase(
            feedback=ManagementCommandWorkspaceBootstrapFeedbackAdapter(command),
            staff_account_seed_use_case=SeedStaffAccountsUseCase(
                staff_account_store=WorkspaceStaffAccountRepository(),
            ),
            setup_bootstrap_use_case=BootstrapWorkspaceSetupUseCase(
                workspace_bootstrap_store=workspace_bootstrap_store,
            ),
            content_bootstrap_use_case=BootstrapWorkspaceContentUseCase(
                workspace_bootstrap_store=workspace_bootstrap_store,
            ),
            finalize_bootstrap_use_case=FinalizeWorkspaceBootstrapUseCase(
                workspace_bootstrap_store=workspace_bootstrap_store,
            ),
        )

from __future__ import annotations

from components.workspace.application.providers.workspace_bootstrap_provider import (
    WorkspaceBootstrapProvider,
)
from components.workspace.application.use_cases.bootstrap_workspace_content_use_case import (
    BootstrapWorkspaceContentUseCase,
)
from components.workspace.application.use_cases.bootstrap_workspace_from_config_use_case import (
    BootstrapWorkspaceFromConfigUseCase,
)
from components.workspace.application.use_cases.bootstrap_workspace_setup_use_case import (
    BootstrapWorkspaceSetupUseCase,
)
from components.workspace.application.use_cases.finalize_workspace_bootstrap_use_case import (
    FinalizeWorkspaceBootstrapUseCase,
)
from components.workspace.application.use_cases.seed_staff_accounts_use_case import (
    SeedStaffAccountsUseCase,
)


def test_workspace_bootstrap_provider_builds_use_case():
    use_case = WorkspaceBootstrapProvider().build_use_case(command=object())

    assert isinstance(use_case, BootstrapWorkspaceFromConfigUseCase)
    assert use_case.feedback.__class__.__name__ == "ManagementCommandWorkspaceBootstrapFeedbackAdapter"
    assert isinstance(use_case.staff_account_seed_use_case, SeedStaffAccountsUseCase)
    assert isinstance(use_case.setup_bootstrap_use_case, BootstrapWorkspaceSetupUseCase)
    assert isinstance(use_case.content_bootstrap_use_case, BootstrapWorkspaceContentUseCase)
    assert isinstance(use_case.finalize_bootstrap_use_case, FinalizeWorkspaceBootstrapUseCase)
    assert (
        use_case.content_bootstrap_use_case.workspace_bootstrap_store
        is use_case.setup_bootstrap_use_case.workspace_bootstrap_store
    )
    assert (
        use_case.finalize_bootstrap_use_case.workspace_bootstrap_store
        is use_case.setup_bootstrap_use_case.workspace_bootstrap_store
    )
    assert use_case.budget_bootstrap_use_case.__class__.__name__ == "BootstrapWorkspaceBudgetUseCase"

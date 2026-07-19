from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from components.workspace.application.ports.workspace_bootstrap_feedback_port import (
    WorkspaceBootstrapFeedbackPort,
)
from components.workspace.application.use_cases.bootstrap_workspace_content_use_case import (
    BootstrapWorkspaceContentUseCase,
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


@dataclass(frozen=True)
class WorkspaceBootstrapResult:
    workspace_id: str
    workspace_name: str
    owner_email: str
    created: bool


@dataclass
class BootstrapWorkspaceFromConfigUseCase:
    feedback: WorkspaceBootstrapFeedbackPort
    staff_account_seed_use_case: SeedStaffAccountsUseCase | Any
    setup_bootstrap_use_case: BootstrapWorkspaceSetupUseCase | Any
    content_bootstrap_use_case: BootstrapWorkspaceContentUseCase | Any
    finalize_bootstrap_use_case: FinalizeWorkspaceBootstrapUseCase | Any

    def execute(
        self,
        config: dict[str, Any],
        *,
        owner_email_override: str | None = None,
        owner_password_override: str | None = None,
    ) -> WorkspaceBootstrapResult:
        staff_members = config.get("staff", [])
        config_dir = Path(config.get("__config_dir", Path.cwd()))
        setup_result = self.setup_bootstrap_use_case.execute(
            config,
            owner_email_override=owner_email_override,
            owner_password_override=owner_password_override,
        )
        self._emit_success(f"Using workspace owner: {setup_result.owner.email}")
        if setup_result.created:
            self._emit_success(f"Created workspace: {setup_result.workspace.workspace_name}")
        else:
            self._emit_notice(f"Updated existing workspace: {setup_result.workspace.workspace_name}")

        self.staff_account_seed_use_case.execute(
            staff_members,
            staff_team=setup_result.staff_team,
            contributors_team=setup_result.contributors_team,
        )
        content_result = self.content_bootstrap_use_case.execute(
            config,
            config_dir=config_dir,
            workspace=setup_result.workspace,
            owner=setup_result.owner,
            staff_team=setup_result.staff_team,
            contributors_team=setup_result.contributors_team,
        )
        for project_title in content_result.project_titles:
            self._emit_success(f"Added project: {project_title}")
        for warning in content_result.pdf_warnings:
            self._emit("WARNING", warning)
        self.finalize_bootstrap_use_case.execute(
            owner=setup_result.owner,
            workspace=setup_result.workspace,
            active_team_id=setup_result.contributors_team.id,
            theme_spec=config["workspace"].get("theme"),
        )

        self._emit_success(f"Workspace '{setup_result.workspace.workspace_name}' is ready.")
        return WorkspaceBootstrapResult(
            workspace_id=str(setup_result.workspace.id),
            workspace_name=setup_result.workspace.workspace_name,
            owner_email=setup_result.owner.email,
            created=setup_result.created,
        )

    def _emit_success(self, message: str) -> None:
        self.feedback.success(message)

    def _emit_notice(self, message: str) -> None:
        self.feedback.notice(message)

    def _emit(self, style_name: str, message: str) -> None:
        if style_name == "WARNING":
            self.feedback.warning(message)

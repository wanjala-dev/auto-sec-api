from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.workspace.application.ports.workspace_bootstrap_port import WorkspaceBootstrapPort


@dataclass(frozen=True)
class BootstrapWorkspaceSetupResult:
    owner: Any
    workspace: Any
    created: bool
    contributors_team: Any
    staff_team: Any
    budget: Any


@dataclass
class BootstrapWorkspaceSetupUseCase:
    workspace_bootstrap_store: WorkspaceBootstrapPort

    def execute(
        self,
        config: dict[str, Any],
        *,
        owner_email_override: str | None = None,
        owner_password_override: str | None = None,
    ) -> BootstrapWorkspaceSetupResult:
        owner_info = config["owner"]
        workspace_info = config["workspace"]
        lookup_info = config.get("workspace_lookup") or workspace_info.get("lookup")
        staff_team_title = config.get("staff_team_title", "Staff Team")

        owner = self.workspace_bootstrap_store.ensure_owner(
            owner_info=owner_info,
            owner_email_override=owner_email_override,
            owner_password_override=owner_password_override,
        )
        workspace, created = self.workspace_bootstrap_store.ensure_workspace(
            owner=owner,
            workspace_info=workspace_info,
            lookup_info=lookup_info,
        )
        self.workspace_bootstrap_store.assign_categories(
            workspace=workspace,
            workspace_info=workspace_info,
        )
        self.workspace_bootstrap_store.assign_contribution_means(
            workspace=workspace,
            workspace_info=workspace_info,
        )
        self.workspace_bootstrap_store.ensure_subscription_plans()
        # "General" home team for teamspaces ("Contributors" collided with the
        # Contributor persona — nav rework); "Family" for personal workspaces.
        default_team_title = "Family" if workspace.sector_id == "personal" else "General"
        contributors_team, budget = self.workspace_bootstrap_store.ensure_workspace_scaffolding(
            workspace=workspace,
            owner=owner,
            team_title=default_team_title,
        )
        staff_team = self.workspace_bootstrap_store.ensure_staff_team(
            workspace=workspace,
            owner=owner,
            title=staff_team_title,
        )
        return BootstrapWorkspaceSetupResult(
            owner=owner,
            workspace=workspace,
            created=created,
            contributors_team=contributors_team,
            staff_team=staff_team,
            budget=budget,
        )

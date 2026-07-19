from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from components.workspace.application.ports.workspace_bootstrap_port import WorkspaceBootstrapPort


@dataclass(frozen=True)
class BootstrapWorkspaceContentResult:
    project_titles: list[str]
    pdf_warnings: list[str]


@dataclass
class BootstrapWorkspaceContentUseCase:
    workspace_bootstrap_store: WorkspaceBootstrapPort

    def execute(
        self,
        config: dict[str, Any],
        *,
        config_dir: Path,
        workspace: Any,
        owner: Any,
        staff_team: Any,
        contributors_team: Any,
    ) -> BootstrapWorkspaceContentResult:
        self.workspace_bootstrap_store.ensure_contributor_user(
            contributor_info=config.get("contributor"),
            workspace=workspace,
            contributors_team=contributors_team,
        )
        project_titles = self.workspace_bootstrap_store.seed_projects(
            projects=config.get("projects", []),
            workspace=workspace,
            team=staff_team,
            owner=owner,
        )
        self.workspace_bootstrap_store.seed_recipients(
            recipients=config.get("recipients", []),
            workspace=workspace,
            owner=owner,
            category_config=config.get("recipients_category"),
        )
        self.workspace_bootstrap_store.seed_news(
            news_items=config.get("news", []),
            workspace=workspace,
            owner=owner,
        )
        pdf_warnings = self.workspace_bootstrap_store.seed_pdfs(
            pdfs=config.get("pdfs", []),
            workspace=workspace,
            owner=owner,
            config_dir=config_dir,
        )
        return BootstrapWorkspaceContentResult(
            project_titles=list(project_titles),
            pdf_warnings=list(pdf_warnings),
        )

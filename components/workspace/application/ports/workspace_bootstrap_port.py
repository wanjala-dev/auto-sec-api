from __future__ import annotations

from typing import Any, Protocol


class WorkspaceBootstrapPort(Protocol):
    def ensure_owner(
        self,
        *,
        owner_info: dict[str, Any],
        owner_email_override: str | None = None,
        owner_password_override: str | None = None,
    ) -> Any: ...

    def ensure_workspace(
        self,
        *,
        owner: Any,
        workspace_info: dict[str, Any],
        lookup_info: dict[str, Any] | None = None,
    ) -> tuple[Any, bool]: ...

    def assign_categories(
        self,
        *,
        workspace: Any,
        workspace_info: dict[str, Any],
    ) -> None: ...

    def assign_contribution_means(
        self,
        *,
        workspace: Any,
        workspace_info: dict[str, Any],
    ) -> None: ...

    def ensure_subscription_plans(self) -> None: ...

    def ensure_workspace_scaffolding(
        self,
        *,
        workspace: Any,
        owner: Any,
        team_title: str,
    ) -> tuple[Any, Any]: ...

    def ensure_staff_team(
        self,
        *,
        workspace: Any,
        owner: Any,
        title: str,
    ) -> Any: ...

    def ensure_contributor_user(
        self,
        *,
        contributor_info: dict[str, Any] | None,
        workspace: Any,
        contributors_team: Any,
    ) -> Any: ...

    def ensure_theme(
        self,
        *,
        workspace: Any,
        theme_spec: dict[str, Any] | None = None,
    ) -> Any: ...

    def finalize_owner_profile(
        self,
        *,
        owner: Any,
        workspace_id: Any,
        active_team_id: Any,
    ) -> None: ...

    def ensure_workspace_follower(
        self,
        *,
        workspace: Any,
        user: Any,
    ) -> None: ...

    def seed_projects(
        self,
        *,
        projects: list[dict[str, Any]],
        workspace: Any,
        team: Any,
        owner: Any,
    ) -> list[str]: ...

    def seed_recipients(
        self,
        *,
        recipients: list[dict[str, Any]],
        workspace: Any,
        owner: Any,
        category_config: dict[str, Any] | None,
    ) -> None: ...

    def seed_news(
        self,
        *,
        news_items: list[dict[str, Any]],
        workspace: Any,
        owner: Any,
    ) -> None: ...

    def seed_pdfs(
        self,
        *,
        pdfs: list[dict[str, Any]],
        workspace: Any,
        owner: Any,
        config_dir: Any,
    ) -> list[str]: ...

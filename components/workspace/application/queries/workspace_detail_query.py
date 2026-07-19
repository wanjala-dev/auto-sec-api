"""Query: Fetch workspace detail with conditional includes.

No Django imports — depends only on port.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.workspace.application.ports.workspace_detail_query_port import (
    WorkspaceDetailData,
    WorkspaceDetailQueryPort,
)


@dataclass(frozen=True)
class WorkspaceDetailRequest:
    """Parsed include parameters for workspace detail."""

    include_teams: bool = True
    include_projects: bool = True
    include_users: bool = True
    include_categories: bool = True
    include_teams_summary: bool = False


class FetchWorkspaceDetailQuery:
    """Application query for workspace detail composition."""

    def __init__(self, query_port: WorkspaceDetailQueryPort) -> None:
        self._port = query_port

    def execute(self, *, workspace: Any, request: WorkspaceDetailRequest) -> WorkspaceDetailData:
        return self._port.fetch_detail(
            workspace=workspace,
            include_teams=request.include_teams,
            include_projects=request.include_projects,
            include_users=request.include_users,
            include_categories=request.include_categories,
            include_teams_summary=request.include_teams_summary,
        )

    @staticmethod
    def parse_include_param(include_param: str | None) -> WorkspaceDetailRequest:
        """Parse the `?include=` query parameter into a typed request."""
        if include_param is None:
            return WorkspaceDetailRequest()

        trimmed = include_param.strip()
        if trimmed == "":
            return WorkspaceDetailRequest(
                include_teams=False,
                include_projects=False,
                include_users=False,
                include_categories=False,
            )

        include = {item.strip() for item in trimmed.split(",") if item.strip()}
        include_teams_summary = "teams_summary" in include
        return WorkspaceDetailRequest(
            include_teams="teams" in include or include_teams_summary,
            include_projects="projects" in include,
            include_users="users" in include,
            include_categories="categories" in include,
            include_teams_summary=include_teams_summary,
        )

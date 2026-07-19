"""Port for workspace detail read queries.

Abstracts the multi-model ORM graph fetched by WorkspaceDetail.retrieve()
so the controller only handles serialization and response assembly.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkspaceDetailData:
    """Raw model collections returned by the workspace detail query."""

    teams: list[Any] = field(default_factory=list)
    projects_by_team: dict[Any, list[Any]] = field(default_factory=dict)
    workspace_projects: list[Any] = field(default_factory=list)
    associated_users: list[Any] = field(default_factory=list)
    categories: list[Any] = field(default_factory=list)


class WorkspaceDetailQueryPort(abc.ABC):
    """Read-only interface for workspace detail composition queries."""

    @abc.abstractmethod
    def fetch_detail(
        self,
        *,
        workspace: Any,
        include_teams: bool = True,
        include_projects: bool = True,
        include_users: bool = True,
        include_categories: bool = True,
        include_teams_summary: bool = False,
    ) -> WorkspaceDetailData:
        """Fetch the full workspace detail graph with conditional includes."""

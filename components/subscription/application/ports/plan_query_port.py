"""Port: Plan lookup and quota queries.

No Django imports — depends only on standard library.
Other contexts (project, team) use this port to check plan limits
without coupling to the Plan model directly.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanQuota:
    """Quota limits for a plan."""

    max_projects_per_team: int = 0
    max_members_per_team: int = 0
    max_tasks_per_project: int = 0


@dataclass(frozen=True)
class PlanInfo:
    """Read-only plan summary for cross-context use."""

    id: str
    title: str
    quota: PlanQuota
    price: int = 0
    billing_interval: str = "month"
    is_default: bool = False


class PlanQueryPort(abc.ABC):
    """Secondary port for plan lookups and quota queries."""

    @abc.abstractmethod
    def get_plan_for_team(self, *, team_id: str) -> PlanInfo | None:
        """Return the plan assigned to a team, or None if no plan."""
        ...

    @abc.abstractmethod
    def get_plan_for_workspace(self, *, workspace_id: str) -> PlanInfo | None:
        """Return the plan assigned to a workspace, or None if no plan."""
        ...

    @abc.abstractmethod
    def get_default_plan(self) -> PlanInfo | None:
        """Return the default (free) plan."""
        ...

    @abc.abstractmethod
    def list_available_plans(self) -> list[PlanInfo]:
        """Return all available plans for display."""
        ...

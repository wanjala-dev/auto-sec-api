"""Port: Project creation operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateProjectCommand:
    title: str
    team_id: str
    user_id: str
    workspace_id: str | None = None
    # When True, mint a project-scoped Budget alongside the project and
    # attach it as Project.budget. Default False preserves the existing
    # behaviour of assigning the first available workspace budget.
    create_dedicated_budget: bool = False


@dataclass
class CreateProjectResult:
    success: bool = True
    project: Any = None


class CreateProjectPort(abc.ABC):
    """Secondary port for project creation."""

    @abc.abstractmethod
    def create_project(self, *, command: CreateProjectCommand) -> CreateProjectResult:
        """Create a project in a team.

        Validates team active status, membership, workspace match,
        plan limits, budget existence, creates the project.

        Raises TeamNotFoundError if team does not exist or is not active.
        Raises TeamMembershipRequiredError if user lacks team access.
        Raises TaskValidationError for cross-validation failures.
        Raises ProjectLimitExceededError if plan limit reached.
        Raises BudgetRequiredError if workspace has no budget.
        """
        ...

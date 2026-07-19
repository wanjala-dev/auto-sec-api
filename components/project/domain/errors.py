"""Domain errors for the project bounded context.

No Django / DRF imports — extends the shared kernel taxonomy.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class ProjectError(DomainError):
    """Base class for all project domain errors."""


class ProjectNotFoundError(ProjectError, NotFoundError):
    """Raised when a project cannot be found."""


class ColumnNotFoundError(ProjectError, NotFoundError):
    """Raised when a column cannot be found."""


class TaskNotFoundError(ProjectError, NotFoundError):
    """Raised when a task cannot be found."""


class TaskValidationError(ProjectError, ValidationError):
    """Raised when a task fails validation."""


class TaskLimitExceededError(ProjectError, ValidationError):
    """Raised when a project exceeds its plan's task limit."""


class ProjectLimitExceededError(ProjectError, ValidationError):
    """Raised when a team exceeds its plan's project limit."""


class BudgetRequiredError(ProjectError, ValidationError):
    """Raised when a workspace has no budget for project creation."""


class TeamNotFoundError(ProjectError, NotFoundError):
    """Raised when a team cannot be found."""


class TeamMembershipRequiredError(ProjectError, AuthorizationError):
    """Raised when a user is not a member of the required team."""


class WorkspaceMembershipRequiredError(ProjectError, AuthorizationError):
    """Raised when a user is not a member of the required workspace."""

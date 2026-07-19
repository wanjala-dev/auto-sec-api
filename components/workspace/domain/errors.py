"""Workspace bounded-context domain errors.

Maps to the shared taxonomy in ``components.shared_kernel.domain.errors``.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class WorkspaceDomainError(DomainError):
    """Base error for workspace domain workflows."""


class WorkspaceNotFoundError(WorkspaceDomainError, NotFoundError):
    """A workspace could not be located."""


class TeamNotFoundError(WorkspaceDomainError, NotFoundError):
    """A team could not be located."""


class WorkspaceValidationError(WorkspaceDomainError, ValidationError):
    """Input or state does not satisfy workspace preconditions."""


class TeamValidationError(WorkspaceDomainError, ValidationError):
    """Input or state does not satisfy team preconditions."""


class InvitationValidationError(WorkspaceDomainError, ValidationError):
    """Invitation data is invalid or expired."""


class TeamConflictError(WorkspaceDomainError, ConflictError):
    """A team with conflicting identity already exists."""


class WorkspaceAuthorizationError(WorkspaceDomainError, AuthorizationError, PermissionError):
    """Caller lacks permission for the workspace operation.

    Also extends ``PermissionError`` for backward compatibility with
    existing controller ``except PermissionError`` catch blocks.
    """


class TeamMembershipRequiredError(WorkspaceAuthorizationError):
    """Caller must be a member of the team."""


class WorkspaceMembershipRequiredError(WorkspaceAuthorizationError):
    """Caller must belong to the organization."""


class WorkspaceAdminRequiredError(WorkspaceAuthorizationError):
    """Caller must be a workspace admin."""


class ProjectNotFoundError(WorkspaceDomainError, NotFoundError):
    """A project could not be located."""


class ColumnNotFoundError(WorkspaceDomainError, NotFoundError):
    """A column could not be located."""


class TaskNotFoundError(WorkspaceDomainError, NotFoundError):
    """A task could not be located."""


class TaskValidationError(WorkspaceDomainError, ValidationError):
    """Task input or state does not satisfy preconditions."""


class TaskLimitExceededError(WorkspaceDomainError, ValidationError):
    """Project has reached maximum task count for its plan."""


class ProjectLimitExceededError(WorkspaceDomainError, ValidationError):
    """Team has reached maximum project count for its plan."""


class BudgetRequiredError(WorkspaceDomainError, ValidationError):
    """Workspace must have a budget before creating a project."""


class JoinRequestNotFoundError(WorkspaceDomainError, NotFoundError):
    """A workspace join request could not be located."""


class JoinRequestValidationError(WorkspaceDomainError, ValidationError):
    """Input or state does not satisfy join request preconditions."""


class JoinRequestAlreadyExistsError(WorkspaceDomainError, ConflictError):
    """A pending join request already exists for this requester + workspace."""


class JoinRequestPermissionError(WorkspaceAuthorizationError):
    """Caller lacks permission to act on the join request."""

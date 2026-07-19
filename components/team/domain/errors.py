"""Domain errors for the team bounded context.

No Django / DRF imports — extends the shared kernel taxonomy.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class TeamError(DomainError):
    """Base class for all team domain errors."""


class TeamNotFoundError(TeamError, NotFoundError):
    """Raised when a team cannot be found."""


class TeamMembershipRequiredError(TeamError, AuthorizationError):
    """Raised when a user is not a member of the required team."""


class TeamInvitationNotFoundError(TeamError, NotFoundError):
    """Raised when a team invitation cannot be found."""


class TeamInvitationExpiredError(TeamError, ValidationError):
    """Raised when a team invitation has expired."""


class TeamInvitationAlreadyAcceptedError(TeamError, ConflictError):
    """Raised when a team invitation was already accepted."""


class TeamMemberLimitExceededError(TeamError, ValidationError):
    """Raised when a team exceeds its plan's member limit."""


class TeamValidationError(TeamError, ValidationError):
    """Raised when team data fails validation."""


class InvitationValidationError(TeamError, ValidationError):
    """Raised when invitation data fails validation."""


class WorkspaceAuthorizationError(TeamError, AuthorizationError):
    """Raised when a workspace-level authorization check fails."""


class WorkspaceAdminRequiredError(TeamError, AuthorizationError):
    """Raised when admin privileges are required for the workspace."""


class WorkspaceValidationError(TeamError, ValidationError):
    """Raised when workspace data fails validation."""


class WorkspaceMembershipRequiredError(TeamError, AuthorizationError):
    """Raised when a user is not a member of the required workspace."""


class TeamConflictError(TeamError, ConflictError):
    """Raised when a team operation conflicts with existing state."""


class TeamPermissionError(TeamError, AuthorizationError):
    """Raised when a user lacks permission for a team operation."""

"""Domain errors for the membership bounded context.

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


class MembershipError(DomainError):
    """Base class for all membership domain errors."""


class MembershipNotFoundError(MembershipError, NotFoundError):
    """Raised when a membership record cannot be found."""


class InvitationNotFoundError(MembershipError, NotFoundError):
    """Raised when an invitation cannot be found."""


class InvitationExpiredError(MembershipError, ValidationError):
    """Raised when an invitation has expired."""


class InvitationAlreadyAcceptedError(MembershipError, ConflictError):
    """Raised when an invitation was already accepted."""


class InsufficientRoleError(MembershipError, AuthorizationError):
    """Raised when a user lacks the required role for an operation."""


class WorkspaceMembershipRequiredError(MembershipError, AuthorizationError):
    """Raised when a user is not a member of the workspace."""


class TeamMembershipRequiredError(MembershipError, AuthorizationError):
    """Raised when a user is not a member of the required team."""


class MembershipValidationError(MembershipError, ValidationError):
    """Raised when membership data fails validation."""


class MembershipConflictError(MembershipError, ConflictError):
    """Raised when a membership already exists."""


class MembershipAuthorizationError(MembershipError, AuthorizationError):
    """Raised when a user lacks authorization for a membership operation."""


class InvitationValidationError(MembershipError, ValidationError):
    """Raised when invitation data fails validation."""


class TeamCapacityExceededError(MembershipError, ValidationError):
    """Raised when a team has reached its maximum member capacity."""


class WorkspaceAdminRequiredError(MembershipError, AuthorizationError):
    """Raised when only workspace admins can perform the operation."""

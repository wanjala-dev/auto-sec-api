"""Identity bounded-context domain errors.

Maps to the shared taxonomy in ``components.shared_kernel.domain.errors``.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class IdentityDomainError(DomainError):
    """Base error for identity domain workflows."""


class UserNotFoundError(IdentityDomainError, NotFoundError):
    """A user or profile could not be located."""


class IdentityValidationError(IdentityDomainError, ValidationError):
    """Identity input does not satisfy preconditions."""


class AuthenticationFailedError(IdentityDomainError, AuthorizationError):
    """Authentication credentials are invalid."""


class SessionNotFoundError(IdentityDomainError, NotFoundError):
    """A login session does not exist or belongs to another user."""


class MissingSessionClaimError(IdentityDomainError, ValidationError):
    """The access token carries no ``sid`` claim (pre-registry token)."""


class LoginActivityEventNotFoundError(IdentityDomainError, NotFoundError):
    """A login-activity audit event does not exist, is not a login-ish
    event, or does not belong to a member of the given workspace."""


class OrgAuditLogDisabledError(IdentityDomainError, AuthorizationError):
    """The workspace admin turned the org audit-log surface OFF.

    Visibility only — auth events keep recording. Maps to 403 at the
    HTTP edge; ``code`` is surfaced in the response body so the
    frontend can render a "turned off" state instead of a generic
    permission error.
    """

    code = "org_audit_log_disabled"

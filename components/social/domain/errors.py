"""Social bounded-context error taxonomy.

Extends the shared kernel so controllers can catch at the taxonomy level
(``DomainError``, ``AuthorizationError``) for uniform HTTP mapping.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    NotFoundError,
    ValidationError,
)


class PostValidationError(ValidationError):
    """The post payload is syntactically or semantically invalid."""


class PostNotFoundError(NotFoundError):
    """The requested post does not exist or has been soft-deleted."""


class PostAuthorizationError(AuthorizationError):
    """Caller is not allowed to create/edit/delete the post."""


class FeedAuthorizationError(AuthorizationError):
    """Caller is not allowed to read this workspace's feed."""

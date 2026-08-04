"""Context-specific exceptions for the tag vocabulary (ADR 0015).

Subclasses of the shared kernel taxonomy so controllers/middleware can catch at
the taxonomy level for uniform HTTP mapping (NotFound → 404, Validation → 400,
Conflict → 409)."""

from __future__ import annotations

from components.shared_kernel.domain.errors import ConflictError, NotFoundError, ValidationError


class TagNotFoundError(NotFoundError):
    """The requested tag does not exist in this workspace."""

    api_code = "not_found"


class InvalidTagError(ValidationError):
    """The tag name/slug/namespace/color does not satisfy the normalization rules."""

    api_code = "invalid_tag"


class DuplicateTagError(ConflictError):
    """A live tag with the same (workspace, slug) identity already exists."""

    api_code = "duplicate_tag"


class ReservedTagError(ValidationError):
    """The operation targets a platform-reserved tag: a ``kind="system"`` tag or a
    system-only namespace (``risk:``). User writes are rejected (D4)."""

    api_code = "reserved_tag"


class TagLimitExceededError(ValidationError):
    """A count limit was hit: tags-per-finding (50) or live tags per workspace (1,000)."""

    api_code = "tag_limit_exceeded"

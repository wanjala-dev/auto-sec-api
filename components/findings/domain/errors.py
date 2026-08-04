"""Context-specific exceptions for the findings SSOT.

Subclasses of the shared kernel taxonomy so controllers/middleware can catch at the
taxonomy level for uniform HTTP mapping (NotFound → 404, Validation → 400)."""

from __future__ import annotations

from components.shared_kernel.domain.errors import NotFoundError, ValidationError


class FindingNotFoundError(NotFoundError):
    """The requested finding does not exist in this workspace."""


class InvalidFindingActionError(ValidationError):
    """The requested lifecycle action is not one this context supports."""

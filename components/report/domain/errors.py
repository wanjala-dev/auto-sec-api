"""Report context domain errors.

Extend the shared exception taxonomy so controllers + middleware map them to
uniform HTTP responses and can catch at the taxonomy level.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
)


class ReportError(DomainError):
    """Base class for report-context domain errors."""


class ReportNotFound(NotFoundError):
    """The requested report does not exist in the caller's workspace."""


class ReportNotApproved(ConflictError):
    """A download was attempted before the report was approved."""


class ReportNotReady(ConflictError):
    """A download/approve was attempted before the PDF finished generating."""


class ReportGenerationError(ReportError):
    """Assembly or rendering failed."""

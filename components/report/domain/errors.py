"""Report context domain errors."""

from __future__ import annotations


class ReportError(Exception):
    """Base class for report-context domain errors."""


class ReportNotFound(ReportError):
    """The requested report does not exist in the caller's workspace."""


class ReportNotApproved(ReportError):
    """A download was attempted before the report was approved."""


class ReportNotReady(ReportError):
    """A download/approve was attempted before the PDF finished generating."""


class ReportGenerationError(ReportError):
    """Assembly or rendering failed."""

"""Domain errors for the content bounded context.

No Django / DRF imports — extends the shared kernel taxonomy.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import (
    AuthorizationError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class ContentError(DomainError):
    """Base class for all content domain errors."""


class NewsNotFoundError(ContentError, NotFoundError):
    """Raised when a news article cannot be found."""


class CategoryNotFoundError(ContentError, NotFoundError):
    """Raised when a category cannot be found."""


class CommentNotFoundError(ContentError, NotFoundError):
    """Raised when a comment cannot be found."""


class ContentValidationError(ContentError, ValidationError):
    """Raised when content fails validation."""


class ContentPermissionError(ContentError, AuthorizationError):
    """Raised when a user lacks permission for a content operation."""


# ── Newsletter ───────────────────────────────────────────────────────────


class NewsletterError(ContentError):
    """Base class for Newsletter-specific domain errors."""


class NewsletterNotFoundError(NewsletterError, NotFoundError):
    """Raised when a newsletter cannot be found."""


class NewsletterAlreadySentError(NewsletterError, ValidationError):
    """Raised when a Send action targets a newsletter already in SENT status."""


class NewsletterInvalidTransitionError(NewsletterError, ValidationError):
    """Raised when a newsletter status transition is not permitted."""


class NewsletterUnverifiedFiguresError(NewsletterError, ValidationError):
    """Raised when a send is blocked because the rendered copy contains
    numeric figures not grounded in the newsletter's metrics corpus.

    Carries the faithfulness result so the API can surface exactly which
    figures are unverified and offer an explicit human override.
    """

    def __init__(self, result, message: str = ""):
        self.result = result
        super().__init__(
            message or "Newsletter contains figures not grounded in its data."
        )


# ── WritingDraft ─────────────────────────────────────────────────────────


class WritingDraftError(ContentError):
    """Base class for WritingDraft-specific domain errors."""


class WritingDraftNotFoundError(WritingDraftError, NotFoundError):
    """Raised when a writing draft cannot be found."""


class WritingDraftInvalidTransitionError(WritingDraftError, ValidationError):
    """Raised when a draft status transition is not permitted."""


# ── WritingTemplate ──────────────────────────────────────────────────────


class WritingTemplateError(ContentError):
    """Base class for WritingTemplate-specific domain errors."""


class WritingTemplateNotFoundError(WritingTemplateError, NotFoundError):
    """Raised when a writing template cannot be found."""

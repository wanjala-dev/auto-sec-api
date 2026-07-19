"""Provider for the newsletter read repository.

Controllers ask this provider for a reader instance instead of
importing ``NewsletterReadRepository`` directly from infrastructure.
"""

from __future__ import annotations

from typing import Any


class NewsletterReadRepositoryProvider:
    """Driving-side façade for the newsletter read repository."""

    def repository(self) -> Any:
        """Return a fresh ``NewsletterReadRepository`` instance."""
        from components.content.infrastructure.repositories.newsletter_read_repository import (
            NewsletterReadRepository,
        )

        return NewsletterReadRepository()


_default = NewsletterReadRepositoryProvider()


def get_newsletter_read_repository_provider() -> NewsletterReadRepositoryProvider:
    """Return the default provider. Override via monkeypatch in tests."""
    return _default

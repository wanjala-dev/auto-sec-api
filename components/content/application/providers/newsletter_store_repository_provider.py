"""Provider for the newsletter store repository.

Controllers ask this provider for a store instance instead of
importing ``NewsletterStoreRepository`` directly from infrastructure.
"""

from __future__ import annotations

from typing import Any


class NewsletterStoreRepositoryProvider:
    """Driving-side façade for the newsletter store repository."""

    def repository(self) -> Any:
        """Return a fresh ``NewsletterStoreRepository`` instance."""
        from components.content.infrastructure.repositories.newsletter_store_repository import (
            NewsletterStoreRepository,
        )

        return NewsletterStoreRepository()


_default = NewsletterStoreRepositoryProvider()


def get_newsletter_store_repository_provider() -> NewsletterStoreRepositoryProvider:
    """Return the default provider. Override via monkeypatch in tests."""
    return _default

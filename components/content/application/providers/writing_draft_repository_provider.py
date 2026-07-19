"""Provider for the writing-draft repository.

Controllers ask this provider for a repository instance instead of
importing ``WritingDraftRepository`` directly from infrastructure.
Keeps the API layer free of infrastructure imports per the EA
controller→infrastructure boundary rule.

The repository is lazy-imported inside the factory method so module
load is cheap and architecture tests don't trip on a transitive ORM
import at discovery time.
"""

from __future__ import annotations

from typing import Any


class WritingDraftRepositoryProvider:
    """Driving-side façade for the writing-draft repository."""

    def repository(self) -> Any:
        """Return a fresh ``WritingDraftRepository`` instance."""
        from components.content.infrastructure.repositories.writing_draft_repository import (
            WritingDraftRepository,
        )

        return WritingDraftRepository()


_default = WritingDraftRepositoryProvider()


def get_writing_draft_repository_provider() -> WritingDraftRepositoryProvider:
    """Return the default provider. Override via monkeypatch in tests."""
    return _default

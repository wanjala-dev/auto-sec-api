"""Provider for the writing-template repository.

Controllers ask this provider for a repository instance instead of
importing ``WritingTemplateRepository`` directly from infrastructure.
Keeps the API layer free of infrastructure imports per the EA
controller→infrastructure boundary rule.
"""

from __future__ import annotations

from typing import Any


class WritingTemplateRepositoryProvider:
    """Driving-side façade for the writing-template repository."""

    def repository(self) -> Any:
        """Return a fresh ``WritingTemplateRepository`` instance."""
        from components.content.infrastructure.repositories.writing_template_repository import (
            WritingTemplateRepository,
        )

        return WritingTemplateRepository()


_default = WritingTemplateRepositoryProvider()


def get_writing_template_repository_provider() -> WritingTemplateRepositoryProvider:
    """Return the default provider. Override via monkeypatch in tests."""
    return _default

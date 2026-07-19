"""Provider for the template placeholder resolver.

Controllers (newsletter + template render) ask this provider for a
resolver instance instead of importing ``TemplatePlaceholderResolver``
directly from infrastructure.
"""

from __future__ import annotations

from typing import Any


class TemplatePlaceholderProvider:
    """Driving-side façade for the template placeholder resolver."""

    def resolver(self) -> Any:
        """Return a fresh ``TemplatePlaceholderResolver`` instance."""
        from components.content.infrastructure.adapters.template_placeholder_resolver import (
            TemplatePlaceholderResolver,
        )

        return TemplatePlaceholderResolver()


_default = TemplatePlaceholderProvider()


def get_template_placeholder_provider() -> TemplatePlaceholderProvider:
    """Return the default provider. Override via monkeypatch in tests."""
    return _default

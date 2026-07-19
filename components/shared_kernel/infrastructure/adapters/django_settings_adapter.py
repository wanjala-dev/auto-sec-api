"""Driven adapter: ``SettingsPort`` backed by ``django.conf.settings``.

The single legal touchpoint between application config reads and
Django's settings module. Application code never sees Django.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from components.shared_kernel.domain.errors import ConfigurationError


class DjangoSettingsAdapter:
    """Concrete implementation of ``SettingsPort``."""

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(settings, key, default)

    def require(self, key: str) -> Any:
        value = getattr(settings, key, None)
        if value is None or value == "":
            raise ConfigurationError(f"Required setting {key!r} is missing or empty")
        return value

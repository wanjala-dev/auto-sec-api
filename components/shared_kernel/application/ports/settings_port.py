"""Port: read runtime configuration without depending on Django settings.

Application layers must not import ``django.conf``. Anywhere a use case
needs a configuration value (``STRIPE_SECRET_KEY``, ``FRONTEND_URL``,
backend-selector strings, etc.) it consumes this port and the concrete
adapter wires the value from Django settings, environment, or a test
override.
"""

from __future__ import annotations

from typing import Any, Protocol


class SettingsPort(Protocol):
    def get(self, key: str, default: Any = None) -> Any:
        """Return the configured value for ``key`` or ``default``."""
        ...

    def require(self, key: str) -> Any:
        """Return the configured value for ``key`` or raise ConfigurationError."""
        ...

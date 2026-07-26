"""Published seam for workspace's password-setup URL builder.

Building the "set your password" link (used in invitation / invited-user emails)
is a workspace concern. Other contexts that send those emails (membership, team)
reach it through this application-layer provider instead of importing
``workspace.infrastructure.adapters.password_setup_url_builder`` directly —
cross-context infrastructure imports are forbidden (ADR 0004 infra-boundary series).
"""

from __future__ import annotations

from typing import Any


class PasswordSetupUrlProvider:
    """Driving-side facade over the password-setup URL builder."""

    def build_password_setup_url(self, *args: Any, **kwargs: Any) -> str:
        """Build the password-setup URL for a user (passthrough)."""
        from components.workspace.infrastructure.adapters.password_setup_url_builder import (
            build_password_setup_url,
        )

        return build_password_setup_url(*args, **kwargs)


_default = PasswordSetupUrlProvider()


def get_password_setup_url_provider() -> PasswordSetupUrlProvider:
    """Return the default provider — the published seam for the password-setup URL builder."""
    return _default

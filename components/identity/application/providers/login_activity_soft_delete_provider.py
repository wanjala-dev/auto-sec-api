"""Provider for the login-activity soft-delete adapter.

Cross-context callers (recycle_bin) consume this provider instead of
importing the concrete adapter in
``components.identity.infrastructure.adapters.login_activity_soft_delete_adapter``
directly.
"""

from __future__ import annotations

from typing import Any


class LoginActivitySoftDeleteProvider:
    def adapter(self) -> Any:
        from components.identity.infrastructure.adapters.login_activity_soft_delete_adapter import (
            LoginActivitySoftDeleteAdapter,
        )

        return LoginActivitySoftDeleteAdapter()


_default = LoginActivitySoftDeleteProvider()


def get_login_activity_soft_delete_provider() -> LoginActivitySoftDeleteProvider:
    return _default

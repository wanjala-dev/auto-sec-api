"""Provider for identity user-utility helpers (static-device lookup, etc.).

Controllers go through this provider instead of importing the concrete
``user_utils`` adapter directly.
"""

from __future__ import annotations

from typing import Any


class UserUtilsProvider:
    def get_user_static_device(self, *args, **kwargs) -> Any:
        from components.identity.infrastructure.adapters.user_utils import (
            get_user_static_device,
        )

        return get_user_static_device(*args, **kwargs)

    def otp_is_verified(self, *args, **kwargs) -> bool:
        from components.identity.infrastructure.adapters.user_utils import (
            otp_is_verified,
        )

        return otp_is_verified(*args, **kwargs)


_default = UserUtilsProvider()


def get_user_utils_provider() -> UserUtilsProvider:
    return _default

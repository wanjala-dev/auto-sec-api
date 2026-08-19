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

    def otp_challenge_token_class(self) -> type:
        """The JWT class minted as a login's ``preauth_token``.

        Returned as a class (not an instance) because SimpleJWT decodes a raw
        token by *constructing* the token class. Only the OTP-completion
        authentication class should ever ask for this — see
        ``components/identity/api/authentication.py``.
        """
        from components.identity.infrastructure.adapters.otp_challenge_token import (
            OtpChallengeToken,
        )

        return OtpChallengeToken


_default = UserUtilsProvider()


def get_user_utils_provider() -> UserUtilsProvider:
    return _default

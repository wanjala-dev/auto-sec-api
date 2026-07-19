"""SimpleJWT adapter implementing TokenPort.

This adapter wraps the existing token issuance logic from infrastructure.persistence.users.utils
behind the identity port contract.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.token_port import TokenPort
from components.identity.domain.value_objects.auth_tokens import AuthTokenPair, PreAuthToken


class JWTTokenAdapter(TokenPort):
    """Concrete adapter backed by rest_framework_simplejwt."""

    def issue_tokens(
        self,
        user_id: UUID,
        *,
        otp_verified: bool,
        device_id: int | None,
        include_refresh: bool,
    ) -> AuthTokenPair:
        from components.identity.infrastructure.adapters.user_utils import issue_tokens as _issue_tokens
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)

        # Resolve device if device_id is provided. django_otp.models.Device is
        # ABSTRACT (no manager) — Device.objects.get / Device.DoesNotExist both
        # raised AttributeError and 500'd the OTP-success token-minting path
        # (the last step of a 2FA login). Look the id up in the concrete device
        # classes instead; only device.persistent_id is needed downstream.
        device = None
        if device_id is not None:
            from django_otp.plugins.otp_static.models import StaticDevice
            from django_otp.plugins.otp_totp.models import TOTPDevice

            for model in (TOTPDevice, StaticDevice):
                device = model.objects.filter(id=device_id).first()
                if device is not None:
                    break

        tokens = _issue_tokens(
            user,
            otp_verified=otp_verified,
            device=device,
            include_refresh=include_refresh,
        )
        return AuthTokenPair(
            access=tokens["access"],
            refresh=tokens.get("refresh"),
            refresh_jti=tokens.get("refresh_jti"),
            refresh_expires_at=tokens.get("refresh_expires_at"),
        )

    def issue_preauth_token(self, user_id: UUID, lifetime_minutes: int) -> PreAuthToken:
        from components.identity.infrastructure.adapters.user_utils import issue_preauth_token as _issue_preauth
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)
        # user_utils.issue_preauth_token returns the access-token STRING, not a
        # dict — indexing it with ["access"] raised TypeError and 500'd every
        # 2FA-enabled user's OTP-required login. (Contrast issue_tokens above,
        # which does return a dict.)
        access_token = _issue_preauth(user, lifetime_minutes=lifetime_minutes)
        return PreAuthToken(
            access=access_token,
            requires_otp=True,
        )

    def decode_token(self, token: str) -> UUID | None:
        import jwt
        from django.conf import settings

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            return UUID(str(payload["user_id"]))
        except (jwt.ExpiredSignatureError, jwt.exceptions.DecodeError, KeyError, ValueError):
            return None

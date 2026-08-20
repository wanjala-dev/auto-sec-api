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

    def issue_email_verification_token(self, user_id: UUID) -> str:
        """Mint the confirmation-link token — a distinct type, not a session.

        ``Token.for_user`` stamps ``token_type`` and the class ``lifetime``, so
        the emailed credential is short-lived and undecodable by
        ``JWTAuthentication`` by construction. See ``email_verification_token.py``
        for the incident this replaced.
        """
        from components.identity.infrastructure.adapters.email_verification_token import (
            EmailVerificationToken,
        )
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)
        return str(EmailVerificationToken.for_user(user))

    def decode_email_verification_token(self, token: str) -> UUID | None:
        """Decode a confirmation-link token, rejecting every other token type.

        ``EmailVerificationToken(raw)`` runs SimpleJWT's ``verify()``, which
        checks signature, expiry AND ``token_type`` — so an access, refresh, or
        OTP-challenge token cannot stand in as proof of inbox control.

        The user-id claim is read through SimpleJWT's own ``USER_ID_CLAIM``
        setting, the same source ``for_user`` writes it from, so mint and
        decode cannot drift apart if that setting is ever changed.
        """
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.settings import api_settings

        from components.identity.infrastructure.adapters.email_verification_token import (
            EmailVerificationToken,
        )

        try:
            payload = EmailVerificationToken(token)
            return UUID(str(payload[api_settings.USER_ID_CLAIM]))
        except (TokenError, KeyError, ValueError):
            return None

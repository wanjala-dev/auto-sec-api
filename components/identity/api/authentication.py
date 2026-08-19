"""DRF authentication classes for identity concerns.

The product's default is ``rest_framework_simplejwt.authentication.JWTAuthentication``
(``DEFAULT_AUTHENTICATION_CLASSES`` in ``api/settings/base.py``), which decodes
only the classes listed in ``SIMPLE_JWT["AUTH_TOKEN_CLASSES"]`` — access tokens.
That is the deny-by-default posture that keeps a login's OTP-challenge token
(``preauth_token``) from authenticating the rest of the product.

This module holds the single, explicit opt-in to that rule, for the endpoints
whose whole job is to consume the challenge.
"""

from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, Token

from components.identity.application.providers.user_utils_provider import (
    get_user_utils_provider,
)


class OtpChallengeJWTAuthentication(JWTAuthentication):
    """Accept a normal access token OR a login's OTP-challenge token.

    ``/identity/otp/verify/`` and ``/identity/otp/static/verify/`` serve two
    callers and need both token kinds:

    * a user completing a 2FA login presents the ``preauth_token`` — an
      ``OtpChallengeToken``, the only thing that token may ever do;
    * a fully logged-in user enrolling a new TOTP device (or confirming a
      recovery code) presents their normal access token.

    ATTACH THIS TO NOTHING ELSE. Every view that accepts a challenge token is a
    view a password-only attacker can reach without a second factor, so the
    allowlist stays exactly these two endpoints. Widening it is a 2FA bypass —
    see ``otp_challenge_token.py`` for the incident this replaced.
    """

    def auth_token_classes(self) -> tuple[type[Token], ...]:
        """Ordered like SimpleJWT's own ``AUTH_TOKEN_CLASSES`` sweep — the
        common case (a real access token) is tried first.

        The challenge class is resolved through the identity provider rather
        than imported here: ``api/`` must not reach into a concrete
        infrastructure adapter (``tests/architecture/test_cross_context_import_rules.py``).
        """
        return (AccessToken, get_user_utils_provider().otp_challenge_token_class())

    def get_validated_token(self, raw_token: bytes) -> Token:
        """Mirror ``JWTAuthentication.get_validated_token`` over a wider set.

        Upstream reads the class list from settings; this reads it from the
        method above so the widening is scoped to the views that opt in rather
        than applied process-wide.
        """
        messages = []
        for auth_token_class in self.auth_token_classes():
            try:
                return auth_token_class(raw_token)
            except TokenError as exc:
                messages.append(
                    {
                        "token_class": auth_token_class.__name__,
                        "token_type": auth_token_class.token_type,
                        "message": exc.args[0],
                    }
                )

        raise InvalidToken(
            {
                "detail": "Given token not valid for any token type",
                "messages": messages,
            }
        )

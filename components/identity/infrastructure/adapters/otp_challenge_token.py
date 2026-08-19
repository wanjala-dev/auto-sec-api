"""The OTP-challenge token — deliberately NOT an access token.

A 2FA login is a two-step mint (see the ``identity`` skill §1): ``LoginUseCase``
withholds the real token pair once the password checks out and hands back this
short-lived token instead; ``VerifyOTPUseCase`` mints the real pair after the
TOTP/recovery code is verified.

This token used to be a ``rest_framework_simplejwt.tokens.AccessToken`` carrying
an extra ``otp_pending`` claim. Nothing in the authentication path read that
claim, so the "half-authenticated" token was accepted by every
``IsAuthenticated`` endpoint in the product — a complete 2FA bypass for anyone
holding only the password (the 5-minute expiry was no mitigation: the password
re-mints a fresh one on demand). Only two endpoints refused it, and only because
they happened to declare ``IsTwoFactorEnabledAndVerified``.

The fix is structural rather than another claim check. SimpleJWT stamps
``token_type`` into every token and ``Token.verify()`` rejects a token whose type
doesn't match the class decoding it. ``JWTAuthentication`` only decodes the
classes in ``AUTH_TOKEN_CLASSES`` — ``("...tokens.AccessToken",)`` in every
settings module here — so declaring a distinct ``token_type`` makes this token
unusable as an access token **by construction**, everywhere, including the
Channels WebSocket middleware, with no allowlist to keep in sync. Endpoints that
legitimately accept the challenge opt IN via
``components.identity.api.authentication.OtpChallengeJWTAuthentication``.

Do NOT give this class the ``access`` token type, and do not widen
``AUTH_TOKEN_CLASSES`` to include it — either change silently restores the bypass.
"""

from __future__ import annotations

from datetime import timedelta

from rest_framework_simplejwt.tokens import Token

#: Wire-format value of the ``token_type`` claim. Anything that is not an access
#: token is rejected by the default authentication path.
OTP_CHALLENGE_TOKEN_TYPE = "otp_challenge"


class OtpChallengeToken(Token):
    """Short-lived proof that a password check passed, pending the OTP.

    Surfaced to clients as ``preauth_token`` on the login response — the API
    field name is unchanged, only the token's type is.
    """

    token_type = OTP_CHALLENGE_TOKEN_TYPE
    #: Overridden per-mint by ``issue_preauth_token``; a class-level default is
    #: required because ``Token.__init__`` refuses to build a token without one.
    lifetime = timedelta(minutes=5)

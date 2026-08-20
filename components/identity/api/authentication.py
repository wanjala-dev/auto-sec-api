"""DRF authentication classes for identity concerns.

The product's default is ``SessionAwareJWTAuthentication`` below
(``DEFAULT_AUTHENTICATION_CLASSES`` in ``api/settings/base.py``). It decodes
only the classes listed in ``SIMPLE_JWT["AUTH_TOKEN_CLASSES"]`` — access tokens
— which is the deny-by-default posture that keeps a login's OTP-challenge token
(``preauth_token``) from authenticating the rest of the product, and it then
checks the token's session against the registry so a revoked session is really
revoked.

This module also holds the single, explicit opt-in to the token-class rule, for
the endpoints whose whole job is to consume the challenge.
"""

from __future__ import annotations

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, Token

from components.identity.application.providers.user_utils_provider import (
    get_user_utils_provider,
)

#: Claim carrying the login session's identity (the refresh token's jti). Both
#: tokens of a pair are stamped with it by ``user_utils.issue_tokens``.
SESSION_CLAIM = "sid"


class SessionAwareJWTAuthentication(JWTAuthentication):
    """A valid signature is not enough — the session must still be alive.

    A SimpleJWT access token is stateless: once signed it authenticates until
    ``exp``, which is ten days on dev/local and one day in prod. Nothing on the
    request path consulted the session registry, so every revocation surface in
    the product was reporting a success it could not deliver — logout,
    revoke-session, revoke-others, password change, and password reset all
    returned 2xx while the access token they claimed to kill kept working. The
    refresh side was already handled by the simplejwt blacklist; this closes the
    access side, which is the one that mattered most: password reset is the flow
    a compromised user runs, and it was leaving the attacker signed in.

    The check is a single indexed lookup on ``UserSession.refresh_jti`` (UNIQUE),
    and it FAILS CLOSED — an access token with no ``sid`` claim, or a ``sid``
    with no live row behind it, is rejected. Fail-open would have been the
    cheaper choice and would have preserved exactly the hole worth closing: a
    session nothing has a record of is a session nothing can revoke. Every mint
    path in the product registers one (``LoginUseCase``, ``VerifyOTPUseCase``,
    magic link, Google, email verification, invite accept); a new mint path that
    forgets to will fail loudly here rather than issuing an immortal session.

    Consequence to know about: deploying this invalidates access tokens issued
    before it, because their sessions predate the registry. Clients hold a valid
    refresh token and re-authenticate transparently.
    """

    def get_user(self, validated_token):
        """Runs after signature/expiry/type checks, before the user is returned."""
        session_id = validated_token.get(SESSION_CLAIM)
        if not self._session_is_live(session_id):
            # Same shape simplejwt uses for a dead token, so clients treat it
            # like any other expired credential and refresh or re-login.
            raise AuthenticationFailed(
                "This session has been revoked or has expired. Please sign in again.",
                code="session_not_active",
            )
        return super().get_user(validated_token)

    @staticmethod
    def _session_is_live(session_id: str | None) -> bool:
        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        if not session_id:
            return False
        return IdentityProvider.build_session_registry().is_active(refresh_jti=str(session_id))


class OtpChallengeJWTAuthentication(SessionAwareJWTAuthentication):
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

    def get_user(self, validated_token):
        """Apply the session check to access tokens ONLY.

        A challenge token is minted BEFORE any session exists — that is the
        whole point of the two-step login — so it has no ``sid`` and the
        inherited fail-closed check would reject it, breaking every 2FA sign-in.
        Its safety comes from its distinct ``token_type``, which is what stops
        it authenticating anything but these two endpoints; it is not, and never
        was, a session.

        An access token presented here is a fully logged-in user enrolling a new
        device, and gets the full session check like everywhere else.
        """
        if validated_token.get("token_type") == AccessToken.token_type:
            return super().get_user(validated_token)
        return JWTAuthentication.get_user(self, validated_token)

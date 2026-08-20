"""Application use case — exchange a Google ID token for a session.

Framework-free. Token verification (Google libs) and user lookup/
creation + JWT issuance (ORM) both happen behind ports; this use case
is just the orchestrator: verify the token, then authenticate the
identity, mapping a bad/absent token to a clean generic error.

Deliberately mirrors ``VerifyMagicLinkUseCase`` — Google sign-in is
another passwordless path converging on the same session DTO.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.identity.application.ports.google_auth_port import (
    GoogleAuthError,
    GoogleAuthPort,
    GoogleTokenVerifierPort,
)
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_port import TokenPort
from components.identity.domain.value_objects.auth_tokens import RequestContext

@dataclass(frozen=True)
class GoogleAuthChallenge:
    """Google vouched for the identity, but the account still owes a factor.

    Same two-step shape the password login uses: no session yet, just a
    short-lived ``preauth_token`` that can do nothing except complete the OTP
    challenge on ``/identity/otp/verify/``.
    """

    user_id: str
    email: str
    username: str
    preauth_token: str
    created_user: bool


_INVALID_TOKEN = GoogleAuthError(
    code="invalid_token",
    message="Could not verify your Google sign-in. Please try again.",
    status=401,
)


class AuthenticateWithGoogleUseCase:
    #: How long the OTP challenge handed back to a 2FA account stays usable.
    #: Same budget the password login gives it.
    PREAUTH_LIFETIME_MINUTES = 5

    def __init__(
        self,
        *,
        verifier: GoogleTokenVerifierPort,
        google_auth: GoogleAuthPort,
        session_registry: SessionRegistryPort,
        tokens: TokenPort,
    ) -> None:
        self._verifier = verifier
        self._google_auth = google_auth
        self._sessions = session_registry
        self._tokens = tokens

    def execute(
        self,
        *,
        raw_token: str,
        context: RequestContext | None = None,
        request_ip: str | None = None,
    ):
        if not raw_token:
            return _INVALID_TOKEN
        identity = self._verifier.verify(raw_token)
        if identity is None:
            return _INVALID_TOKEN
        if request_ip is None and context is not None:
            request_ip = context.ip_address
        session = self._google_auth.authenticate(identity=identity, request_ip=request_ip)
        if isinstance(session, GoogleAuthError):
            return session
        if session.two_factor_required:
            # No session registered and no pair minted: Google proved who this
            # is, which is one factor. The second one is still owed.
            preauth = self._tokens.issue_preauth_token(
                UUID(str(session.user_id)),
                lifetime_minutes=self.PREAUTH_LIFETIME_MINUTES,
            )
            return GoogleAuthChallenge(
                user_id=str(session.user_id),
                email=session.email,
                username=session.username,
                preauth_token=preauth.access,
                created_user=session.created_user,
            )
        # Register the login session (never breaks sign-in — the adapter
        # logs + continues on failure).
        if session.refresh_jti and session.refresh_expires_at:
            self._sessions.create_session(
                user_id=UUID(str(session.user_id)),
                refresh_jti=session.refresh_jti,
                expires_at=session.refresh_expires_at,
                context=context,
                login_method="google",
            )
        return session

"""Application use case — exchange a Google ID token for a session.

Framework-free. Token verification (Google libs) and user lookup/
creation + JWT issuance (ORM) both happen behind ports; this use case
is just the orchestrator: verify the token, then authenticate the
identity, mapping a bad/absent token to a clean generic error.

Deliberately mirrors ``VerifyMagicLinkUseCase`` — Google sign-in is
another passwordless path converging on the same session DTO.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.google_auth_port import (
    GoogleAuthError,
    GoogleAuthPort,
    GoogleTokenVerifierPort,
)
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.domain.value_objects.auth_tokens import RequestContext

_INVALID_TOKEN = GoogleAuthError(
    code="invalid_token",
    message="Could not verify your Google sign-in. Please try again.",
    status=401,
)


class AuthenticateWithGoogleUseCase:
    def __init__(
        self,
        *,
        verifier: GoogleTokenVerifierPort,
        google_auth: GoogleAuthPort,
        session_registry: SessionRegistryPort,
    ) -> None:
        self._verifier = verifier
        self._google_auth = google_auth
        self._sessions = session_registry

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

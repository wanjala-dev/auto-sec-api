"""Use case: revoke every login session EXCEPT the current one.

Framework-free — ports only. The current session is identified by the
``sid`` claim on the access token that made the request; a token without
a ``sid`` (issued before the session registry shipped) cannot safely
express "everything but me", so the use case refuses (→ 400) rather than
guessing.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_revocation_port import TokenRevocationPort
from components.identity.domain.enums import AuthEventCode
from components.identity.domain.errors import MissingSessionClaimError
from components.identity.domain.value_objects.auth_tokens import RequestContext

REVOKE_REASON = "user_revoked"


class RevokeOtherSessionsUseCase:
    """Blacklist all other active refresh tokens + revoke their sessions."""

    def __init__(
        self,
        *,
        session_registry: SessionRegistryPort,
        token_revocation: TokenRevocationPort,
        audit_port: AuthAuditPort,
    ) -> None:
        self._sessions = session_registry
        self._revocation = token_revocation
        self._audit = audit_port

    def execute(
        self,
        *,
        user_id: UUID,
        current_sid: str | None,
        email: str,
        context: RequestContext,
    ) -> int:
        """Returns the number of sessions revoked."""
        if not current_sid:
            raise MissingSessionClaimError(
                "This access token carries no session claim; log in again before revoking other sessions."
            )

        # Blacklist each other active session's refresh token, then flip
        # the registry rows in one write.
        jtis = self._sessions.list_active_jtis_for_user(user_id=user_id, except_jti=current_sid)
        for jti in jtis:
            self._revocation.revoke_by_jti(jti=jti)

        revoked = self._sessions.revoke_all_for_user(
            user_id=user_id,
            reason=REVOKE_REASON,
            except_jti=current_sid,
        )

        self._audit.record_event(
            event_code=AuthEventCode.SESSION_REVOKED,
            user_id=user_id,
            email=email,
            success=True,
            context=context,
            metadata={
                "scope": "others",
                "revoked_count": revoked,
                "session_jti": current_sid,
            },
        )
        return revoked

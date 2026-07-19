"""Use case: revoke ONE of the user's own login sessions.

Framework-free — ports only. Ownership is enforced through the registry's
user-scoped lookup: an unknown id OR another user's session both raise
``SessionNotFoundError`` (→ 404) so existence is never leaked.

Revoking a session that is already revoked is an idempotent no-op — the
controller still returns 204 and no duplicate audit event is written.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_revocation_port import TokenRevocationPort
from components.identity.domain.enums import AuthEventCode
from components.identity.domain.errors import SessionNotFoundError
from components.identity.domain.value_objects.auth_tokens import RequestContext

REVOKE_REASON = "user_revoked"


class RevokeSessionUseCase:
    """Blacklist the session's refresh token + mark the registry row revoked."""

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
        session_id: UUID,
        email: str,
        context: RequestContext,
    ) -> bool:
        """Returns True when a live session was revoked, False when the
        session was already revoked (idempotent success)."""
        record = self._sessions.get_for_user(user_id=user_id, session_id=session_id)
        if record is None:
            raise SessionNotFoundError("Session not found.")

        if record.revoked_at is not None:
            return False

        # Blacklist the refresh token FIRST — if that fails, the registry
        # row stays active and the operation can be retried cleanly.
        self._revocation.revoke_by_jti(jti=record.refresh_jti)
        self._sessions.revoke(refresh_jti=record.refresh_jti, reason=REVOKE_REASON)

        self._audit.record_event(
            event_code=AuthEventCode.SESSION_REVOKED,
            user_id=user_id,
            email=email,
            success=True,
            context=context,
            metadata={
                "scope": "single",
                "revoked_session_id": str(session_id),
                "session_jti": record.refresh_jti,
            },
        )
        return True

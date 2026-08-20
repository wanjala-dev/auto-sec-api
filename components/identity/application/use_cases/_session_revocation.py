"""Shared choreography: end a user's login sessions, for real.

Ending a session takes TWO writes that must always happen together:

1. blacklist the session's refresh token, so it can't mint new access tokens;
2. flip the ``UserSession`` row to revoked, so ``SessionAwareJWTAuthentication``
   stops honouring the access tokens already in the wild.

Doing only (1) is what the product used to do on password change and password
reset — nothing at all, in fact — and doing only (2) would leave the refresh
token minting replacements. Three callers need this exact pair now
(``RevokeOtherSessionsUseCase``, ``ChangePasswordUseCase``,
``SetNewPasswordUseCase``), so it lives here once rather than being copied and
drifting: a fix applied to one copy and not the others is how half-revoked
sessions come back.

Framework-free — ports only.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_revocation_port import TokenRevocationPort


def revoke_sessions_for_user(
    *,
    sessions: SessionRegistryPort,
    token_revocation: TokenRevocationPort,
    user_id: UUID,
    reason: str,
    except_jti: str | None = None,
) -> int:
    """Blacklist + revoke every active session for ``user_id``.

    ``except_jti`` spares one session — used by password CHANGE, where the
    caller is the legitimate owner acting from a device they are already on and
    should not be logged out of. Password RESET passes nothing: it is the
    recovery flow, the person may be recovering from a compromise, and the whole
    point is that nothing survives it.

    Returns the number of sessions revoked.
    """
    for jti in sessions.list_active_jtis_for_user(user_id=user_id, except_jti=except_jti):
        token_revocation.revoke_by_jti(jti=jti)
    return sessions.revoke_all_for_user(user_id=user_id, reason=reason, except_jti=except_jti)

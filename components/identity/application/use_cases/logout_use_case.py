"""Logout use case — handles token revocation and audit trail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_revocation_port import TokenRevocationPort
from components.identity.domain.enums import AuthEventCode
from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass(frozen=True)
class LogoutCommand:
    user_id: Any
    email: str
    all_devices: bool
    context: RequestContext
    # jti of the refresh token submitted with the logout request (None when
    # the client sent no/an undecodable refresh token). Lets single-device
    # logout revoke exactly its own session.
    refresh_jti: str | None = None


class LogoutUseCase:
    """Revoke tokens + sessions and record an audit event for user logout."""

    def __init__(
        self,
        *,
        token_revocation: TokenRevocationPort,
        audit_port: AuthAuditPort,
        session_registry: SessionRegistryPort,
    ):
        self._revocation = token_revocation
        self._audit = audit_port
        self._sessions = session_registry

    def execute(self, command: LogoutCommand) -> int:
        """Execute logout. Returns count of tokens revoked (0 if single-device)."""
        revoked = 0
        if command.all_devices:
            revoked = self._revocation.revoke_all_tokens(user_id=command.user_id)
            self._sessions.revoke_all_for_user(user_id=command.user_id, reason="logout")
        elif command.refresh_jti:
            # Single-device logout: the controller's serializer already
            # blacklisted the submitted refresh token; mirror that on the
            # session registry for exactly that session.
            self._sessions.revoke(refresh_jti=command.refresh_jti, reason="logout")

        self._audit.record_event(
            event_code=AuthEventCode.LOGOUT,
            user_id=command.user_id,
            email=command.email,
            success=True,
            context=command.context,
            metadata={"all_devices": command.all_devices, "tokens_revoked": revoked},
        )
        return revoked

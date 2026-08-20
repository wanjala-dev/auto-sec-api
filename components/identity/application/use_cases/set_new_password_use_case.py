"""Use case: Set a new password after reset token validation.

Validates the reset token, sets the new password, and records audit events.
No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.identity.application.commands.reset_password_command import (
    SetNewPasswordCommand,
    SetNewPasswordFailure,
    SetNewPasswordResult,
)
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.password_reset_port import PasswordResetPort
from components.identity.application.ports.security_notification_port import SecurityNotificationPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_revocation_port import TokenRevocationPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort
from components.identity.application.use_cases._session_revocation import revoke_sessions_for_user
from components.identity.domain.enums import AuthEventCode


class SetNewPasswordUseCase:
    """Application use case for setting a new password after reset."""

    def __init__(
        self,
        *,
        reset_port: PasswordResetPort,
        audit_port: AuthAuditPort,
        notification_port: SecurityNotificationPort,
        user_repo: UserRepositoryPort,
        session_registry: SessionRegistryPort,
        token_revocation: TokenRevocationPort,
    ) -> None:
        self._reset = reset_port
        self._audit = audit_port
        self._notification = notification_port
        self._user_repo = user_repo
        self._sessions = session_registry
        self._revocation = token_revocation

    def execute(self, command: SetNewPasswordCommand) -> SetNewPasswordResult | SetNewPasswordFailure:
        """Execute the set-new-password flow."""
        # 1. Validate token
        user_id = self._reset.validate_reset_token(command.uidb64, command.token)
        if user_id is None:
            return SetNewPasswordFailure(
                reason="invalid_token",
                message="Token is not valid, please request a new one",
            )

        # 2. Enforce the password policy — the SAME chain as change-password.
        #    Reset-complete previously accepted a top-10 common password that
        #    /identity/changepassword/ would have refused.
        policy_errors = self._user_repo.validate_new_password(user_id, command.new_password)
        if policy_errors:
            return SetNewPasswordFailure(
                reason="weak_password",
                message=" ".join(policy_errors),
            )

        # 3. Set new password
        self._reset.set_new_password(user_id, command.new_password)

        # 3b. End EVERY session — nothing is spared. This is the account
        #     recovery flow: the person running it may be locking an attacker
        #     out, and the caller here is unauthenticated, so there is no
        #     session that has earned the right to survive. Previously reset
        #     revoked nothing at all, which meant a compromised account stayed
        #     compromised for the full refresh lifetime after the victim did the
        #     one thing the product tells them to do.
        revoked_sessions = revoke_sessions_for_user(
            sessions=self._sessions,
            token_revocation=self._revocation,
            user_id=user_id,
            reason="password_reset",
        )

        # 3. Record audit event
        self._audit.record_event(
            event_code=AuthEventCode.PASSWORD_RESET_COMPLETED,
            user_id=user_id,
            email="",
            success=True,
            context=command.context,
            metadata={"revoked_sessions": revoked_sessions},
        )

        # 4. Notify
        self._notification.notify_security_event(
            actor_id=None,
            user_id=user_id,
            verb="reset password",
            event_code=AuthEventCode.PASSWORD_RESET_COMPLETED,
            metadata={"ip": command.context.ip_address},
        )

        return SetNewPasswordResult()

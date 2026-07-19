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
from components.identity.domain.enums import AuthEventCode
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.password_reset_port import PasswordResetPort
from components.identity.application.ports.security_notification_port import SecurityNotificationPort


class SetNewPasswordUseCase:
    """Application use case for setting a new password after reset."""

    def __init__(
        self,
        *,
        reset_port: PasswordResetPort,
        audit_port: AuthAuditPort,
        notification_port: SecurityNotificationPort,
    ) -> None:
        self._reset = reset_port
        self._audit = audit_port
        self._notification = notification_port

    def execute(self, command: SetNewPasswordCommand) -> SetNewPasswordResult | SetNewPasswordFailure:
        """Execute the set-new-password flow."""
        # 1. Validate token
        user_id = self._reset.validate_reset_token(command.uidb64, command.token)
        if user_id is None:
            return SetNewPasswordFailure(
                reason="invalid_token",
                message="Token is not valid, please request a new one",
            )

        # 2. Set new password
        self._reset.set_new_password(user_id, command.new_password)

        # 3. Record audit event
        self._audit.record_event(
            event_code=AuthEventCode.PASSWORD_RESET_COMPLETED,
            user_id=user_id,
            email="",
            success=True,
            context=command.context,
            metadata=None,
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

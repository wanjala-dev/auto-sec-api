"""Change-password use case — framework-free business orchestration.

Flow:
1. Verify old password matches
2. Reject if new password equals old password
3. Validate new password against password policy
4. Confirm new password matches confirmation
5. Set new password
6. Record audit event
7. Dispatch security notification
"""

from __future__ import annotations

from components.identity.application.commands.change_password_command import (
    ChangePasswordCommand,
    ChangePasswordFailure,
    ChangePasswordResult,
)
from components.identity.domain.enums import AuthEventCode
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.security_notification_port import SecurityNotificationPort
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.application.ports.token_revocation_port import TokenRevocationPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort
from components.identity.application.use_cases._session_revocation import revoke_sessions_for_user


class ChangePasswordUseCase:
    """Orchestrate a user-initiated password change."""

    def __init__(
        self,
        *,
        user_repo: UserRepositoryPort,
        audit_port: AuthAuditPort,
        notification_port: SecurityNotificationPort,
        session_registry: SessionRegistryPort,
        token_revocation: TokenRevocationPort,
    ) -> None:
        self._user_repo = user_repo
        self._audit_port = audit_port
        self._notification_port = notification_port
        self._sessions = session_registry
        self._revocation = token_revocation

    def execute(
        self, command: ChangePasswordCommand
    ) -> ChangePasswordResult | ChangePasswordFailure:
        # 1. Verify old password
        if not self._user_repo.check_password(command.user_id, command.old_password):
            return ChangePasswordFailure(
                field="old_password",
                messages=["Incorrect password."],
            )

        # 2. Reject same-as-old
        if self._user_repo.check_password(command.user_id, command.new_password):
            return ChangePasswordFailure(
                field="new_password",
                messages=["New password cannot be the same as old password."],
            )

        # 3. Validate password policy
        validation_errors = self._user_repo.validate_new_password(
            command.user_id, command.new_password
        )
        if validation_errors:
            return ChangePasswordFailure(
                field="new_password",
                messages=validation_errors,
            )

        # 4. Confirm match
        if command.new_password != command.confirm_password:
            return ChangePasswordFailure(
                field="confirm_password",
                messages=["New passwords do not match."],
            )

        # 5. Set new password
        self._user_repo.set_password(command.user_id, command.new_password)

        # 5b. End every OTHER session. Changing a password is how a user says
        #     "someone else may have this" — leaving the other sessions alive
        #     made the act cosmetic: the old access tokens kept working for the
        #     full ACCESS_TOKEN_LIFETIME and their refresh tokens kept minting
        #     new ones. The caller's own session is spared (`command.session_jti`)
        #     so a routine password change doesn't log you out of the device you
        #     just used; when the claim is absent, nothing is spared.
        revoked_sessions = revoke_sessions_for_user(
            sessions=self._sessions,
            token_revocation=self._revocation,
            user_id=command.user_id,
            reason="password_changed",
            except_jti=getattr(command, "session_jti", None),
        )

        # 6. Audit
        self._audit_port.record_event(
            event_code=AuthEventCode.PASSWORD_CHANGED,
            user_id=command.user_id,
            email=command.email,
            success=True,
            context=command.context,
            metadata={"revoked_sessions": revoked_sessions},
        )

        # 7. Security notification
        self._notification_port.notify_security_event(
            actor_id=command.user_id,
            user_id=command.user_id,
            verb="changed password",
            event_code=AuthEventCode.PASSWORD_CHANGED,
            metadata={
                "ip": command.context.ip_address,
                "user_agent": command.context.user_agent,
            },
        )

        return ChangePasswordResult(
            success=True,
            message="Password updated successfully",
        )

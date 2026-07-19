"""Use case: Request a password reset email.

Orchestrates reset token generation, email dispatch, and audit recording.
No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.identity.application.commands.reset_password_command import (
    RequestPasswordResetCommand,
    RequestPasswordResetResult,
)
from components.identity.domain.enums import AuthEventCode
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.password_reset_port import PasswordResetPort
from components.identity.application.ports.security_notification_port import SecurityNotificationPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort


class RequestPasswordResetUseCase:
    """Application use case for requesting a password reset."""

    def __init__(
        self,
        *,
        user_repo: UserRepositoryPort,
        reset_port: PasswordResetPort,
        audit_port: AuthAuditPort,
        notification_port: SecurityNotificationPort,
    ) -> None:
        self._user_repo = user_repo
        self._reset = reset_port
        self._audit = audit_port
        self._notification = notification_port

    def execute(self, command: RequestPasswordResetCommand) -> RequestPasswordResetResult:
        """Execute the password reset request flow.

        Always returns success to prevent email enumeration.
        """
        email = (command.email or "").strip().lower()
        user = self._user_repo.find_by_email(email)

        if user is not None:
            # Generate reset token
            token_info = self._reset.generate_reset_token(user.id)

            # Build reset URL. Point at the canonical frontend route
            # (/identity/password-reset-confirm/<uid>/<token>/) directly —
            # the legacy /PasswordResetConfirm/... path only resolves via a
            # client-side redirect, so linking it risks a 404 if that
            # redirect ever drops the params. rstrip the base so a trailing
            # slash on the frontend base doesn't produce a double slash.
            reset_path = (
                f"/identity/password-reset-confirm/"
                f"{token_info.uidb64}/{token_info.token}/"
            )
            reset_url = f"{command.reset_base_url.rstrip('/')}{reset_path}"
            if command.redirect_url:
                reset_url = f"{reset_url}?redirect_url={command.redirect_url}"

            # Send email
            self._reset.send_reset_email(email=user.email, reset_url=reset_url)

            # Record audit event
            self._audit.record_event(
                event_code=AuthEventCode.PASSWORD_RESET_REQUESTED,
                user_id=user.id,
                email=user.email,
                success=True,
                context=command.context,
                metadata=None,
            )

            # Notify
            self._notification.notify_security_event(
                actor_id=None,
                user_id=user.id,
                verb="requested a password reset",
                event_code=AuthEventCode.PASSWORD_RESET_REQUESTED,
                metadata={"ip": command.context.ip_address},
            )

        # Always return success to prevent email enumeration
        return RequestPasswordResetResult()

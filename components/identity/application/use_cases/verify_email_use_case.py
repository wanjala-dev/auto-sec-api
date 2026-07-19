"""Use case: Verify a user's email address via token.

Decodes the verification token, marks the user's email as verified,
records the audit event, and issues fresh tokens. No Django imports —
depends only on ports.
"""

from __future__ import annotations

from components.identity.application.commands.verify_email_command import (
    VerifyEmailCommand,
    VerifyEmailFailure,
    VerifyEmailResult,
)
from components.identity.domain.enums import AuthEventCode
from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.token_port import TokenPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort


class VerifyEmailUseCase:
    """Application use case for email verification."""

    def __init__(
        self,
        *,
        user_repo: UserRepositoryPort,
        token_port: TokenPort,
        audit_port: AuthAuditPort,
    ) -> None:
        self._user_repo = user_repo
        self._tokens = token_port
        self._audit = audit_port

    def execute(self, command: VerifyEmailCommand) -> VerifyEmailResult | VerifyEmailFailure:
        """Execute the email verification flow."""
        context = command.context

        # 1. Decode the verification token
        user_id = self._tokens.decode_token(command.token)
        if user_id is None:
            self._audit.record_event(
                event_code=AuthEventCode.EMAIL_VERIFY,
                user_id=None,
                email="",
                success=False,
                context=context,
                metadata={"reason": "token_invalid_or_expired"},
            )
            return VerifyEmailFailure(
                reason="token_invalid",
                message="Invalid or expired token",
            )

        # 2. Find the user
        user = self._user_repo.find_by_id(user_id)
        if user is None:
            self._audit.record_event(
                event_code=AuthEventCode.EMAIL_VERIFY,
                user_id=user_id,
                email="",
                success=False,
                context=context,
                metadata={"reason": "user_not_found"},
            )
            return VerifyEmailFailure(
                reason="user_not_found",
                message="User not found",
            )

        # 3. Mark email as verified (idempotent)
        if not user.is_verified:
            self._user_repo.verify_email(user_id)

        # 4. Record success audit event
        self._audit.record_event(
            event_code=AuthEventCode.EMAIL_VERIFY,
            user_id=user_id,
            email=user.email,
            success=True,
            context=context,
            metadata=None,
        )

        # 5. Issue fresh tokens
        token_pair = self._tokens.issue_tokens(
            user_id,
            otp_verified=False,
            device_id=None,
            include_refresh=True,
        )
        tokens = {"access": token_pair.access}
        if token_pair.refresh:
            tokens["refresh"] = token_pair.refresh

        return VerifyEmailResult(
            user_id=user.id,
            email=user.email,
            username=user.username,
            is_onboard_complete=user.is_onboard_complete,
            is_contributor=user.is_contributor,
            tokens=tokens,
        )

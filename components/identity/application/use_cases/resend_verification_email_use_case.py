"""Use case: Resend the account-verification email (public recovery path).

Behind the always-202 ``/identity/resend-verification/`` endpoint. The
response never differs by account state (no account-existence oracle) —
this use case silently no-ops for unknown or already-verified addresses
and only queues a fresh verification email (and audit event) for an
unverified account. Framework-free — depends only on ports.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.identity.application.ports.auth_audit_port import AuthAuditPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort
from components.identity.application.ports.verification_email_dispatch_port import (
    VerificationEmailDispatchPort,
)
from components.identity.domain.enums import AuthEventCode
from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass(frozen=True)
class ResendVerificationEmailCommand:
    """Input DTO for the resend-verification flow."""

    email: str
    context: RequestContext


class ResendVerificationEmailUseCase:
    """Queue a fresh verification email for an unverified account.

    Returns nothing distinguishable to the caller — the HTTP layer always
    answers 202 regardless of outcome.
    """

    def __init__(
        self,
        *,
        user_repo: UserRepositoryPort,
        audit_port: AuthAuditPort,
        dispatch_port: VerificationEmailDispatchPort,
    ) -> None:
        self._user_repo = user_repo
        self._audit = audit_port
        self._dispatch = dispatch_port

    def execute(self, command: ResendVerificationEmailCommand) -> None:
        email = (command.email or "").strip().lower()
        if not email:
            return

        user = self._user_repo.find_by_email(email)
        if user is None or user.is_verified:
            # No oracle: unknown and already-verified addresses are silent
            # no-ops (already-verified users can simply sign in).
            return

        self._dispatch.queue_verification_email(user.id)
        self._audit.record_event(
            event_code=AuthEventCode.EMAIL_VERIFICATION_RESENT,
            user_id=user.id,
            email=email,
            success=True,
            context=command.context,
            metadata={"reason": "user_requested_resend"},
        )

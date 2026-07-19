"""Use case: Register a new user and send verification email.

Orchestrates user creation, token generation for email verification,
and verification email dispatch. No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.identity.application.commands.register_command import (
    RegisterCommand,
    RegisterResult,
)
from components.identity.application.ports.email_verification_port import EmailVerificationPort
from components.identity.application.ports.token_port import TokenPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort


class RegisterUserUseCase:
    """Application use case for user registration."""

    def __init__(
        self,
        *,
        user_repo: UserRepositoryPort,
        token_port: TokenPort,
        email_port: EmailVerificationPort,
    ) -> None:
        self._user_repo = user_repo
        self._tokens = token_port
        self._email = email_port

    def execute(self, command: RegisterCommand) -> RegisterResult:
        """Execute the registration flow.

        Creates the user, issues a verification token, and sends the
        confirmation email.
        """
        # 1. Create the user
        user = self._user_repo.create_user(
            username=command.username,
            email=command.email,
            password=command.password,
        )

        # 2. Issue a short-lived access token for email verification link
        token_pair = self._tokens.issue_tokens(
            user.id,
            otp_verified=False,
            device_id=None,
            include_refresh=False,
        )
        verification_url = f"{command.confirmation_base_url}?token={token_pair.access}"

        # 3. Send verification email
        email_sent = self._email.send_verification_email(
            user_id=user.id,
            email=user.email,
            username=user.username,
            verification_url=verification_url,
            site_name=command.site_name,
            site_domain=command.site_domain,
        )

        warning = None
        if not email_sent:
            warning = "Account created, but verification email could not be sent right now."

        return RegisterResult(
            user_id=user.id,
            email=user.email,
            username=user.username,
            email_sent=email_sent,
            warning=warning,
        )

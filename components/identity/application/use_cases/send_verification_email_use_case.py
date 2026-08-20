"""Use case: Build and send one verification email for an unverified user.

Runs inside the background worker (driven by the
``identity.send_verification_email`` Celery task). Mints a fresh
short-lived verification token, builds the confirmation URL, and hands the
message to the email port. Framework-free — depends only on ports.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.email_verification_port import EmailVerificationPort
from components.identity.application.ports.token_port import TokenPort
from components.identity.application.ports.user_repository_port import UserRepositoryPort


class SendVerificationEmailUseCase:
    """Send the account-verification email to a single user.

    Idempotent + honest:
      * user gone        → ``skipped_missing`` (nothing to do)
      * already verified → ``skipped_verified`` (never spam a verified inbox)
      * otherwise        → sends and returns ``sent``; a send failure RAISES
        so the Celery task retries instead of claiming success.
    """

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

    def execute(
        self,
        *,
        user_id: UUID,
        confirmation_base_url: str,
        site_name: str,
        site_domain: str,
    ) -> str:
        user = self._user_repo.find_by_id(user_id)
        if user is None:
            return "skipped_missing"
        if user.is_verified:
            return "skipped_verified"

        # A single-purpose, short-lived token — NOT an access token. This link
        # travels by plaintext email and then sits in an inbox; an access token
        # here made the confirmation link a full-privilege session on an
        # account that had not yet passed the verification gate.
        verification_token = self._tokens.issue_email_verification_token(user.id)
        verification_url = f"{confirmation_base_url}?token={verification_token}"

        self._email.send_verification_email(
            user_id=user.id,
            email=user.email,
            username=user.username,
            verification_url=verification_url,
            site_name=site_name,
            site_domain=site_domain,
        )
        return "sent"

"""Port for password reset token generation and email dispatch.

The application layer calls this port; infrastructure provides the
adapter that generates reset tokens and sends emails.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class PasswordResetTokenInfo:
    """Value object for a generated password reset token."""

    uidb64: str
    token: str


class PasswordResetPort(ABC):
    """Secondary/driven port for password reset operations."""

    @abstractmethod
    def generate_reset_token(self, user_id: UUID) -> PasswordResetTokenInfo:
        """Generate a uidb64/token pair for password reset."""
        ...

    @abstractmethod
    def send_reset_email(
        self,
        *,
        email: str,
        reset_url: str,
    ) -> bool:
        """Send a password reset email. Returns True if sent successfully."""
        ...

    @abstractmethod
    def validate_reset_token(self, uidb64: str, token: str) -> UUID | None:
        """Validate a reset token and return the user_id, or None if invalid."""
        ...

    @abstractmethod
    def set_new_password(self, user_id: UUID, password: str) -> None:
        """Set a new password for the user."""
        ...

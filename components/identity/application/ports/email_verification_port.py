"""Port for sending email verification messages.

The application layer calls this port; infrastructure provides the
adapter that sends the actual email (Django EmailMultiAlternatives, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class EmailVerificationPort(ABC):
    """Secondary/driven port for verification email dispatch."""

    @abstractmethod
    def send_verification_email(
        self,
        *,
        user_id: UUID,
        email: str,
        username: str,
        verification_url: str,
        site_name: str,
        site_domain: str,
    ) -> bool:
        """Send a verification/confirmation email.

        Returns True if the email was sent successfully, False otherwise.
        """
        ...

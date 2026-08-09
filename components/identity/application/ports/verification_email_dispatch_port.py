"""Port for queueing verification-email delivery.

The application layer asks for a verification email to be delivered
*eventually* (fire-and-forget); infrastructure decides how (Celery task).
Distinct from ``EmailVerificationPort``, which performs the actual
synchronous send inside the background worker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class VerificationEmailDispatchPort(ABC):
    """Secondary/driven port for asynchronous verification-email dispatch."""

    @abstractmethod
    def queue_verification_email(self, user_id: UUID) -> None:
        """Queue a verification email for the given user.

        Implementations MUST be safe to call inside a database transaction
        (deliver after commit) and MUST NOT block the request path on the
        actual SMTP send.
        """
        ...

"""Infrastructure adapter implementing VerificationEmailDispatchPort.

Queues the ``identity.send_verification_email`` Celery task so the SMTP
send never blocks the request path (>100ms rule). Dispatches after the
surrounding database transaction commits — the task re-reads the user row,
so it must not race an uncommitted registration.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.identity.application.ports.verification_email_dispatch_port import (
    VerificationEmailDispatchPort,
)

logger = logging.getLogger(__name__)


class CeleryVerificationEmailDispatchAdapter(VerificationEmailDispatchPort):
    """Queue verification-email delivery through Celery, post-commit."""

    def queue_verification_email(self, user_id: UUID) -> None:
        from django.db import transaction

        from components.identity.workers.tasks import send_verification_email

        def _enqueue() -> None:
            send_verification_email.delay(str(user_id))
            logger.info("verification_email_queued user_id=%s", user_id)

        transaction.on_commit(_enqueue)

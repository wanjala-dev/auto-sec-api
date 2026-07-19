"""ORM implementation of ``NewsletterDispatchLedgerPort`` (task #25).

Every write is row-level (bulk_create, UPDATE … WHERE, F() increments) —
no request-time aggregation anywhere; the artifact's counters are
denormalized exactly so list cards read them for free.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from components.content.application.ports.newsletter_dispatch_ledger_port import (
    NewsletterDispatchLedgerPort,
)

logger = logging.getLogger(__name__)


class NewsletterDispatchLedgerAdapter(NewsletterDispatchLedgerPort):
    def issue(
        self,
        *,
        workspace_id: UUID,
        newsletter_id: UUID,
        emails: Sequence[str],
    ) -> dict[str, str]:
        from infrastructure.persistence.content.models import EmailDispatchRecord

        records = [
            EmailDispatchRecord(
                workspace_id=workspace_id,
                newsletter_id=newsletter_id,
                recipient_email=email,
            )
            for email in emails
        ]
        EmailDispatchRecord.objects.bulk_create(records)
        return {record.recipient_email: str(record.open_token) for record in records}

    def finalize(
        self,
        *,
        newsletter_id: UUID,
        delivered_emails: Sequence[str],
        failed_emails: Sequence[str],
    ) -> None:
        from infrastructure.persistence.content.models import (
            EmailDispatchRecord,
            Newsletter,
        )

        if delivered_emails:
            EmailDispatchRecord.objects.filter(
                newsletter_id=newsletter_id,
                recipient_email__in=list(delivered_emails),
                status=EmailDispatchRecord.STATUS_PENDING,
            ).update(status=EmailDispatchRecord.STATUS_SENT)
        if failed_emails:
            EmailDispatchRecord.objects.filter(
                newsletter_id=newsletter_id,
                recipient_email__in=list(failed_emails),
                status=EmailDispatchRecord.STATUS_PENDING,
            ).update(status=EmailDispatchRecord.STATUS_FAILED)

        Newsletter.objects.filter(id=newsletter_id).update(
            recipient_count=len(delivered_emails),
            failed_count=len(failed_emails),
        )
        logger.info(
            "newsletter_dispatch_finalized newsletter_id=%s delivered=%d failed=%d",
            newsletter_id,
            len(delivered_emails),
            len(failed_emails),
        )

    def record_open(self, *, open_token: UUID) -> bool:
        from infrastructure.persistence.content.models import (
            EmailDispatchRecord,
            Newsletter,
        )

        record = (
            EmailDispatchRecord.objects.filter(open_token=open_token)
            .only("id", "newsletter_id", "first_opened_at")
            .first()
        )
        if record is None:
            return False

        now = timezone.now()
        is_first_open = record.first_opened_at is None
        EmailDispatchRecord.objects.filter(id=record.id).update(
            open_count=F("open_count") + 1,
            last_opened_at=now,
            **({"first_opened_at": now} if is_first_open else {}),
        )
        if record.newsletter_id:
            Newsletter.objects.filter(id=record.newsletter_id).update(
                total_open_count=F("total_open_count") + 1,
                last_opened_at=now,
                **({"unique_open_count": F("unique_open_count") + 1} if is_first_open else {}),
            )
        return True

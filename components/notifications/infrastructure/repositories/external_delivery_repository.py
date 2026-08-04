"""ORM implementation of the external-delivery ledger (ADR 0016 D7)."""

from __future__ import annotations

import logging
from uuid import UUID

from django.db import IntegrityError
from django.db.models import F

from components.notifications.application.ports.external_delivery_ledger_port import (
    ExternalDeliveryLedgerPort,
    LedgerRecord,
)

logger = logging.getLogger(__name__)

_MAX_ERROR_LENGTH = 500


class ExternalDeliveryRepository(ExternalDeliveryLedgerPort):
    def record(self, *, connection_id: UUID, dedup_key: str, event_key: str) -> LedgerRecord:
        """Reserve the (connection, dedup_key) pair.

        Leans on the DB unique constraint rather than a read-then-write check —
        losing that race costs a duplicate message in a customer's channel.
        """
        from infrastructure.persistence.notifications.models import ExternalDelivery

        try:
            row, created = ExternalDelivery.objects.get_or_create(
                connection_id=connection_id,
                dedup_key=dedup_key,
                defaults={"event_key": event_key},
            )
        except IntegrityError:
            # Lost the insert race — re-read the winner's row and let ``claim``
            # decide which worker actually delivers.
            row = ExternalDelivery.objects.get(connection_id=connection_id, dedup_key=dedup_key)
            created = False
        return LedgerRecord(id=row.id, created=created, status=row.status)

    def claim(self, record_id: int) -> bool:
        """Atomically move a deliverable row to ``sending``.

        The conditional UPDATE is the whole mechanism: the database decides the
        winner, so exactly one worker sees a rowcount of 1. ``sent`` and ``skipped``
        are excluded, which is what makes redelivery of an already-sent event
        impossible; ``failed`` is included, which is what lets a Celery retry work.
        """
        from infrastructure.persistence.notifications.models import ExternalDelivery

        claimed = (
            ExternalDelivery.objects.filter(
                id=record_id,
                status__in=(ExternalDelivery.Status.PENDING, ExternalDelivery.Status.FAILED),
            )
            .update(status=ExternalDelivery.Status.SENDING, attempts=F("attempts") + 1)
        )
        return claimed == 1

    def mark_sent(self, record_id: int) -> None:
        from infrastructure.persistence.notifications.models import ExternalDelivery

        ExternalDelivery.objects.filter(id=record_id).update(
            status=ExternalDelivery.Status.SENT, last_error=""
        )

    def mark_failed(self, record_id: int, error: str) -> None:
        from infrastructure.persistence.notifications.models import ExternalDelivery

        ExternalDelivery.objects.filter(id=record_id).update(
            status=ExternalDelivery.Status.FAILED,
            last_error=(error or "")[:_MAX_ERROR_LENGTH],
        )

    def mark_skipped(self, record_id: int, reason: str) -> None:
        from infrastructure.persistence.notifications.models import ExternalDelivery

        ExternalDelivery.objects.filter(id=record_id).update(
            status=ExternalDelivery.Status.SKIPPED,
            last_error=(reason or "")[:_MAX_ERROR_LENGTH],
        )

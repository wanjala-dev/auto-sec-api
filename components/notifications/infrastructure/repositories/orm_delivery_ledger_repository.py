"""ORM adapter implementing DeliveryLedgerPort.

Idempotency comes from the DB-level unique constraint on
(notification, channel, subscription) — ``record()`` is get_or_create so a
retried dispatch converges on the same row.
"""

from __future__ import annotations

import logging

from components.notifications.application.ports.delivery_ledger_port import (
    DeliveryLedgerPort,
    DeliveryRecord,
    RecordOutcome,
)

logger = logging.getLogger(__name__)


def _to_record(obj) -> DeliveryRecord:
    return DeliveryRecord(
        id=str(obj.id),
        notification_id=str(obj.notification_id),
        channel=obj.channel,
        subscription_id=str(obj.subscription_id) if obj.subscription_id else None,
        status=obj.status,
        attempts=obj.attempts,
        last_error=obj.last_error,
    )


class OrmDeliveryLedgerRepository(DeliveryLedgerPort):
    """Concrete adapter backed by the ``NotificationDelivery`` model."""

    def record(self, *, notification_id, channel, subscription_id=None) -> RecordOutcome:
        from django.db import IntegrityError

        from infrastructure.persistence.notifications.models import NotificationDelivery

        try:
            delivery, created = NotificationDelivery.objects.get_or_create(
                notification_id=notification_id,
                channel=channel,
                subscription_id=subscription_id,
                defaults={"status": NotificationDelivery.Status.PENDING},
            )
        except IntegrityError:
            # Lost a concurrent race on the unique constraint — the row now
            # exists; fetch it (this IS the idempotency guarantee working).
            delivery = NotificationDelivery.objects.get(
                notification_id=notification_id,
                channel=channel,
                subscription_id=subscription_id,
            )
            created = False
        return RecordOutcome(record=_to_record(delivery), created=created)

    def claim(self, delivery_id) -> DeliveryRecord | None:
        from django.db.models import F

        from infrastructure.persistence.notifications.models import NotificationDelivery

        claimed = NotificationDelivery.objects.filter(
            id=delivery_id,
            status__in=[
                NotificationDelivery.Status.PENDING,
                NotificationDelivery.Status.FAILED,  # failed rows may be retried
            ],
        ).update(attempts=F("attempts") + 1)
        if not claimed:
            return None
        return _to_record(NotificationDelivery.objects.get(id=delivery_id))

    def pending_for(self, *, notification_id, channel) -> list[DeliveryRecord]:
        from infrastructure.persistence.notifications.models import NotificationDelivery

        qs = NotificationDelivery.objects.filter(
            notification_id=notification_id,
            channel=channel,
            status=NotificationDelivery.Status.PENDING,
        ).order_by("created_at")
        return [_to_record(obj) for obj in qs]

    def deliverable_for(self, *, notification_id, channel) -> list[DeliveryRecord]:
        from infrastructure.persistence.notifications.models import NotificationDelivery

        qs = NotificationDelivery.objects.filter(
            notification_id=notification_id,
            channel=channel,
            status__in=[
                NotificationDelivery.Status.PENDING,
                NotificationDelivery.Status.FAILED,  # retryable — mirrors claim()
            ],
        ).order_by("created_at")
        return [_to_record(obj) for obj in qs]

    def mark_sent(self, delivery_id) -> None:
        self._transition(delivery_id, status="sent", error="")

    def mark_failed(self, delivery_id, *, error) -> None:
        self._transition(delivery_id, status="failed", error=error or "")

    def mark_skipped(self, delivery_id, *, reason) -> None:
        self._transition(delivery_id, status="skipped", error=reason or "")

    @staticmethod
    def _transition(delivery_id, *, status, error) -> None:
        from infrastructure.persistence.notifications.models import NotificationDelivery

        updated = NotificationDelivery.objects.filter(id=delivery_id).update(
            status=status,
            last_error=error,
        )
        if not updated:
            logger.warning(
                "delivery_ledger_transition_missing delivery_id=%s status=%s",
                delivery_id,
                status,
            )

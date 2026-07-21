"""ORM adapter implementing PushSubscriptionRegistryPort.

Django ORM stays here — application/domain never touch the model.
"""

from __future__ import annotations

from components.notifications.application.ports.push_subscription_registry_port import (
    PushSubscriptionRecord,
    PushSubscriptionRegistryPort,
    UpsertOutcome,
)


def _to_record(obj) -> PushSubscriptionRecord:
    return PushSubscriptionRecord(
        id=str(obj.id),
        user_id=str(obj.user_id),
        platform=obj.platform,
        endpoint=obj.endpoint,
        endpoint_hash=obj.endpoint_hash,
        keys=dict(obj.keys or {}),
        device_label=obj.device_label,
        status=obj.status,
        last_seen_at=obj.last_seen_at,
    )


class OrmPushSubscriptionRepository(PushSubscriptionRegistryPort):
    """Concrete adapter backed by the ``PushSubscription`` model."""

    def upsert_by_endpoint(
        self,
        *,
        user_id,
        endpoint,
        endpoint_hash,
        keys=None,
        device_label="",
        user_agent="",
        platform="web",
    ) -> UpsertOutcome:
        from django.utils import timezone

        from infrastructure.persistence.notifications.models import PushSubscription

        subscription, created = PushSubscription.objects.update_or_create(
            endpoint_hash=endpoint_hash,
            defaults={
                "user_id": user_id,
                "platform": platform,
                "endpoint": endpoint,
                "keys": keys or {},
                "device_label": device_label,
                "user_agent": user_agent,
                "status": PushSubscription.Status.ACTIVE,
                "last_seen_at": timezone.now(),
            },
        )
        return UpsertOutcome(record=_to_record(subscription), created=created)

    def revoke_by_endpoint_hash(self, *, user_id, endpoint_hash) -> bool:
        from infrastructure.persistence.notifications.models import PushSubscription

        updated = (
            PushSubscription.objects.filter(user_id=user_id, endpoint_hash=endpoint_hash)
            .exclude(status=PushSubscription.Status.REVOKED)
            .update(status=PushSubscription.Status.REVOKED)
        )
        return bool(updated)

    def list_active_for_user(self, user_id, *, platform=None) -> list[PushSubscriptionRecord]:
        from infrastructure.persistence.notifications.models import PushSubscription

        qs = PushSubscription.objects.filter(
            user_id=user_id,
            status=PushSubscription.Status.ACTIVE,
        )
        if platform:
            qs = qs.filter(platform=platform)
        return [_to_record(obj) for obj in qs.order_by("created_at")]

    def get_by_id(self, subscription_id) -> PushSubscriptionRecord | None:
        from infrastructure.persistence.notifications.models import PushSubscription

        obj = PushSubscription.objects.filter(id=subscription_id).first()
        return _to_record(obj) if obj else None

    def mark_expired(self, subscription_id) -> None:
        from infrastructure.persistence.notifications.models import PushSubscription

        PushSubscription.objects.filter(id=subscription_id).update(
            status=PushSubscription.Status.EXPIRED,
        )

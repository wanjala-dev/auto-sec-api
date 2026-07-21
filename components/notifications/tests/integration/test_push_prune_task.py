"""Integration tests for the weekly push/delivery hygiene task.

``notifications.prune_stale_push_subscriptions`` enforces three rules:

1. Dead (expired/revoked) ``PushSubscription`` rows untouched for
   ``PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS`` are deleted.
2. Active subscriptions unseen for ``PUSH_SUBSCRIPTION_STALE_AFTER_DAYS``
   are marked expired (NOT deleted) with ``updated_at`` stamped, so they
   age into rule 1's window on a later run.
3. Terminal (sent/skipped/failed) ``NotificationDelivery`` rows older than
   ``NOTIFICATION_DELIVERY_RETENTION_DAYS`` are deleted; pending rows and
   the ``Notification`` rows themselves are untouched.

Rows are aged via queryset ``update()`` because ``created_at`` /
``updated_at`` are auto fields that ``save()`` would re-stamp.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import count

import pytest
from django.utils import timezone

from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash
from components.notifications.workers.tasks import prune_stale_push_subscriptions
from infrastructure.persistence.notifications.models import (
    Notification,
    NotificationDelivery,
    PushSubscription,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_seq = count(1)


def _days_ago(days):
    return timezone.now() - timedelta(days=days)


def _subscription(
    user,
    *,
    status=PushSubscription.Status.ACTIVE,
    updated_days_ago=None,
    last_seen_days_ago=None,
    created_days_ago=None,
):
    endpoint = f"https://push.example.com/send/prune-device-{next(_seq)}"
    sub = PushSubscription.objects.create(
        user=user,
        endpoint=endpoint,
        endpoint_hash=derive_endpoint_hash(endpoint),
        keys={"p256dh": "BPubKey", "auth": "authsecret"},
        status=status,
        last_seen_at=_days_ago(last_seen_days_ago) if last_seen_days_ago is not None else None,
    )
    aged = {}
    if updated_days_ago is not None:
        aged["updated_at"] = _days_ago(updated_days_ago)
    if created_days_ago is not None:
        aged["created_at"] = _days_ago(created_days_ago)
    if aged:
        PushSubscription.objects.filter(pk=sub.pk).update(**aged)
        sub.refresh_from_db()
    return sub


def _notification(user):
    return Notification.objects.create(
        recipient=user,
        actor=user,
        notification_type=Notification.NotificationType.SYSTEM,
        verb="prune-test",
    )


def _delivery(
    notification, *, status, created_days_ago, subscription=None, channel=NotificationDelivery.Channel.WEB_PUSH
):
    delivery = NotificationDelivery.objects.create(
        notification=notification,
        subscription=subscription,
        channel=channel,
        status=status,
    )
    NotificationDelivery.objects.filter(pk=delivery.pk).update(created_at=_days_ago(created_days_ago))
    delivery.refresh_from_db()
    return delivery


def _run():
    return prune_stale_push_subscriptions.apply().result


class TestDeadSubscriptionPruning:
    def test_old_expired_and_revoked_subscriptions_deleted(self, user_factory):
        user = user_factory()
        old_expired = _subscription(user, status=PushSubscription.Status.EXPIRED, updated_days_ago=91)
        old_revoked = _subscription(user, status=PushSubscription.Status.REVOKED, updated_days_ago=120)

        result = _run()

        assert result["subscriptions_pruned"] == 2
        assert not PushSubscription.objects.filter(pk__in=[old_expired.pk, old_revoked.pk]).exists()

    def test_recently_dead_subscriptions_kept(self, user_factory):
        user = user_factory()
        recent_expired = _subscription(user, status=PushSubscription.Status.EXPIRED, updated_days_ago=30)
        recent_revoked = _subscription(user, status=PushSubscription.Status.REVOKED, updated_days_ago=89)

        result = _run()

        assert result["subscriptions_pruned"] == 0
        assert PushSubscription.objects.filter(pk=recent_expired.pk).exists()
        assert PushSubscription.objects.filter(pk=recent_revoked.pk).exists()

    def test_old_active_subscription_never_deleted_by_rule_one(self, user_factory):
        """Rule 1 only touches dead statuses — an ancient active row is expired, not deleted."""
        user = user_factory()
        sub = _subscription(user, updated_days_ago=400, last_seen_days_ago=400)

        _run()

        assert PushSubscription.objects.filter(pk=sub.pk).exists()


class TestStaleActiveExpiry:
    def test_stale_active_marked_expired_not_deleted(self, user_factory):
        user = user_factory()
        sub = _subscription(user, last_seen_days_ago=181)

        result = _run()

        assert result["subscriptions_expired"] == 1
        sub.refresh_from_db()
        assert sub.status == PushSubscription.Status.EXPIRED
        # updated_at is stamped to "now" so the row gets a full
        # PRUNE_AFTER_DAYS retention window before rule 1 deletes it.
        assert sub.updated_at > _days_ago(1)

    def test_recently_seen_active_kept_active(self, user_factory):
        user = user_factory()
        sub = _subscription(user, last_seen_days_ago=30)

        result = _run()

        assert result["subscriptions_expired"] == 0
        sub.refresh_from_db()
        assert sub.status == PushSubscription.Status.ACTIVE

    def test_never_seen_active_falls_back_to_created_at(self, user_factory):
        user = user_factory()
        stale = _subscription(user, created_days_ago=181, updated_days_ago=181)
        fresh = _subscription(user, created_days_ago=10)

        result = _run()

        assert result["subscriptions_expired"] == 1
        stale.refresh_from_db()
        fresh.refresh_from_db()
        assert stale.status == PushSubscription.Status.EXPIRED
        assert fresh.status == PushSubscription.Status.ACTIVE

    def test_freshly_expired_survives_the_next_run_too(self, user_factory):
        """Two-phase aging: expire on run N, delete only ~90 days later."""
        user = user_factory()
        sub = _subscription(user, updated_days_ago=400, last_seen_days_ago=400)

        first = _run()
        assert first["subscriptions_expired"] == 1
        assert first["subscriptions_pruned"] == 0

        second = _run()
        assert second["subscriptions_expired"] == 0
        assert second["subscriptions_pruned"] == 0
        sub.refresh_from_db()
        assert sub.status == PushSubscription.Status.EXPIRED


class TestDeliveryLedgerRetention:
    def test_old_terminal_deliveries_deleted_notifications_untouched(self, user_factory):
        user = user_factory()
        notifications = [_notification(user) for _ in range(3)]
        statuses = (
            NotificationDelivery.Status.SENT,
            NotificationDelivery.Status.SKIPPED,
            NotificationDelivery.Status.FAILED,
        )
        deliveries = [
            _delivery(notification, status=status, created_days_ago=181)
            for notification, status in zip(notifications, statuses)
        ]

        result = _run()

        assert result["deliveries_pruned"] == 3
        assert not NotificationDelivery.objects.filter(pk__in=[d.pk for d in deliveries]).exists()
        assert Notification.objects.include_archived().filter(pk__in=[n.pk for n in notifications]).count() == 3

    def test_non_terminal_old_delivery_kept(self, user_factory):
        user = user_factory()
        pending = _delivery(_notification(user), status=NotificationDelivery.Status.PENDING, created_days_ago=400)

        result = _run()

        assert result["deliveries_pruned"] == 0
        assert NotificationDelivery.objects.filter(pk=pending.pk).exists()

    def test_recent_terminal_delivery_kept(self, user_factory):
        user = user_factory()
        recent = _delivery(_notification(user), status=NotificationDelivery.Status.SENT, created_days_ago=30)

        result = _run()

        assert result["deliveries_pruned"] == 0
        assert NotificationDelivery.objects.filter(pk=recent.pk).exists()


class TestLedgerSurvivesSubscriptionDeletion:
    def test_delivery_fk_set_null_when_subscription_pruned(self, user_factory):
        user = user_factory()
        sub = _subscription(user, status=PushSubscription.Status.REVOKED, updated_days_ago=120)
        delivery = _delivery(
            _notification(user),
            status=NotificationDelivery.Status.SENT,
            created_days_ago=30,
            subscription=sub,
        )

        result = _run()

        assert result["subscriptions_pruned"] == 1
        assert result["deliveries_pruned"] == 0
        delivery.refresh_from_db()
        assert delivery.subscription is None

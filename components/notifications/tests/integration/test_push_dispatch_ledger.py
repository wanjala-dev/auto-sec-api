"""Integration tests for the per-channel fan-out leg of the dispatch funnel.

Celery runs eagerly under test settings, so a dispatched notification flows
row-creation → realtime publish → channel gate → ledger record →
``deliver_web_push``, all inline. Test settings leave ``WEB_PUSH_ENABLED``
off, so the T1-S6 sender takes its truthful flag-off path: pending
web_push rows transition to ``skipped`` with an explicit reason — the
terminal state asserted here is ``skipped``, never a fake ``sent``.
The enabled-path behaviour lives in ``test_deliver_web_push_task.py``.
"""

from __future__ import annotations

import pytest

from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash
from components.notifications.infrastructure.adapters.notification_service import (
    channels_for,
    invalidate_channel_cache,
)
from components.notifications.infrastructure.tasks.web_push_tasks import (
    WEB_PUSH_SENDER_DISABLED_REASON,
)
from components.notifications.workers.tasks import dispatch_notification_async
from infrastructure.persistence.notifications.models import (
    Notification,
    NotificationDelivery,
    PushSubscription,
)
from infrastructure.persistence.notifications.userpreferences.models import UserPreference

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

ENDPOINT = "https://push.example.com/send/dispatch-device"


def _subscribe(user, suffix=""):
    endpoint = f"{ENDPOINT}{suffix}"
    return PushSubscription.objects.create(
        user=user,
        endpoint=endpoint,
        endpoint_hash=derive_endpoint_hash(endpoint),
        keys={"p256dh": "BPubKey", "auth": "authsecret"},
    )


def _set_prefs(user, **flags):
    """UserPreference is auto-created per user (signal) — mutate, don't create."""
    pref, _ = UserPreference.objects.get_or_create(user=user)
    for name, value in flags.items():
        setattr(pref, name, value)
    if flags:
        pref.save(update_fields=list(flags))
    return pref


def _dispatch(recipient, actor, verb="mentioned you"):
    return dispatch_notification_async.apply(
        kwargs={
            "recipient_id": str(recipient.pk),
            "actor_id": str(actor.pk),
            "verb": verb,
            "notification_type": Notification.NotificationType.MENTION,
        }
    )


class TestChannelsFor:
    def test_defaults_to_realtime_only(self, user_factory):
        user = user_factory()
        assert channels_for(user) == ("realtime",)

    def test_push_pref_enables_web_push(self, user_factory):
        user = user_factory()
        _set_prefs(user, push_notifications=True)
        assert channels_for(user) == ("realtime", "web_push")

    def test_email_pref_enables_email(self, user_factory):
        user = user_factory()
        _set_prefs(user, email_notifications=True)
        assert channels_for(user) == ("realtime", "email")

    def test_decision_is_cached_and_invalidatable(self, user_factory):
        user = user_factory()
        pref = _set_prefs(user)
        assert channels_for(user) == ("realtime",)

        pref.push_notifications = True
        pref.save(update_fields=["push_notifications"])
        # Cached decision still served until the endpoint-side invalidation runs.
        assert channels_for(user) == ("realtime",)

        invalidate_channel_cache(user.pk)
        assert channels_for(user) == ("realtime", "web_push")


class TestDispatchLedger:
    def test_pref_on_with_active_subscription_records_then_skips(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, push_notifications=True)
        subscription = _subscribe(recipient)

        _dispatch(recipient, actor)

        notification = Notification.objects.get(recipient=recipient)
        delivery = NotificationDelivery.objects.get(notification=notification)
        assert delivery.channel == NotificationDelivery.Channel.WEB_PUSH
        assert delivery.subscription_id == subscription.id
        # Eager Celery ran the sender's flag-off path inline: pending →
        # skipped with a truthful reason, never a fake success.
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == WEB_PUSH_SENDER_DISABLED_REASON

    def test_one_ledger_row_per_active_device(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, push_notifications=True)
        _subscribe(recipient, suffix="-a")
        _subscribe(recipient, suffix="-b")

        _dispatch(recipient, actor)

        notification = Notification.objects.get(recipient=recipient)
        assert (
            NotificationDelivery.objects.filter(
                notification=notification,
                channel=NotificationDelivery.Channel.WEB_PUSH,
            ).count()
            == 2
        )

    def test_pref_off_records_no_web_push_rows(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        # push_notifications defaults to False — the dormant boolean gates.
        _set_prefs(recipient)
        _subscribe(recipient)

        _dispatch(recipient, actor)

        assert Notification.objects.filter(recipient=recipient).exists()
        assert not NotificationDelivery.objects.filter(channel=NotificationDelivery.Channel.WEB_PUSH).exists()

    def test_pref_on_without_subscriptions_records_nothing(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, push_notifications=True)

        _dispatch(recipient, actor)

        assert Notification.objects.filter(recipient=recipient).exists()
        assert not NotificationDelivery.objects.exists()

    def test_revoked_subscription_is_not_fanned_out(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, push_notifications=True)
        subscription = _subscribe(recipient)
        subscription.status = PushSubscription.Status.REVOKED
        subscription.save(update_fields=["status"])

        _dispatch(recipient, actor)

        assert not NotificationDelivery.objects.exists()

    def test_redelivery_converges_on_same_ledger_row(self, user_factory):
        """The (notification, channel, subscription) key makes a repeated
        dispatch idempotent — the deduped notification maps onto the same
        ledger row instead of double-recording."""
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, push_notifications=True)
        _subscribe(recipient)

        _dispatch(recipient, actor)
        _dispatch(recipient, actor)  # create_notification dedups to the same row

        assert Notification.objects.filter(recipient=recipient).count() == 1
        assert NotificationDelivery.objects.count() == 1

"""Integration tests for the email leg of the dispatch funnel (T1-S8).

Celery runs eagerly under test settings, so a dispatched notification flows
row-creation → channel gate → EMAIL_WORTHY_TYPES policy → ledger record →
``deliver_email``, all inline. Test settings leave
``NOTIF_EMAIL_CHANNEL_ENABLED`` off, so the sender takes its truthful
flag-off path: pending email rows transition to ``skipped`` with an
explicit reason — never a fake ``sent``. The enabled-path behaviour lives
in ``test_deliver_email_task.py``.

Also proves the T1-S5 known-issue fix: NULL-subscription (email) rows are
deduped at the DB by the conditional unique constraint on
(notification, channel) WHERE subscription IS NULL — enforced on Postgres
AND on the SQLite test schema (unlike ``nulls_distinct``, which Django
skips entirely on SQLite).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from components.notifications.application.providers.push_delivery_provider import (
    get_push_delivery_provider,
)
from components.notifications.infrastructure.tasks.email_tasks import (
    EMAIL_CHANNEL_DISABLED_REASON,
)
from components.notifications.workers.tasks import dispatch_notification_async
from infrastructure.persistence.notifications.models import (
    Notification,
    NotificationDelivery,
)
from infrastructure.persistence.notifications.userpreferences.models import UserPreference

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _set_prefs(user, **flags):
    """UserPreference is auto-created per user (signal) — mutate, don't create."""
    pref, _ = UserPreference.objects.get_or_create(user=user)
    for name, value in flags.items():
        setattr(pref, name, value)
    if flags:
        pref.save(update_fields=list(flags))
    return pref


def _dispatch(recipient, actor, notification_type=Notification.NotificationType.MENTION, verb="mentioned you"):
    return dispatch_notification_async.apply(
        kwargs={
            "recipient_id": str(recipient.pk),
            "actor_id": str(actor.pk),
            "verb": verb,
            "notification_type": notification_type,
        }
    )


def _email_rows(notification=None):
    qs = NotificationDelivery.objects.filter(channel=NotificationDelivery.Channel.EMAIL)
    if notification is not None:
        qs = qs.filter(notification=notification)
    return qs


class TestEmailDispatchLedger:
    def test_pref_on_worthy_type_records_exactly_one_email_row(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, email_notifications=True)

        _dispatch(recipient, actor)

        notification = Notification.objects.get(recipient=recipient)
        delivery = _email_rows(notification).get()
        assert delivery.subscription_id is None
        # Eager Celery ran the sender's flag-off path inline: pending →
        # skipped with a truthful reason, never a fake success.
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == EMAIL_CHANNEL_DISABLED_REASON

    def test_double_dispatch_converges_on_one_email_row(self, user_factory):
        """The dedup fix: repeated dispatch of the deduped notification maps
        onto the SAME NULL-subscription ledger row instead of double-recording
        (the T1-S5 NULLs-distinct hole, closed by the conditional constraint)."""
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, email_notifications=True)

        _dispatch(recipient, actor)
        _dispatch(recipient, actor)  # create_notification dedups to the same row

        assert Notification.objects.filter(recipient=recipient).count() == 1
        assert _email_rows().count() == 1

    def test_unworthy_type_records_no_email_row(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient, email_notifications=True)

        _dispatch(recipient, actor, notification_type=Notification.NotificationType.LIKE, verb="liked your post")

        assert Notification.objects.filter(recipient=recipient).exists()
        assert not _email_rows().exists()

    def test_pref_off_records_no_email_row(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        _set_prefs(recipient)  # email_notifications defaults to False

        _dispatch(recipient, actor)

        assert Notification.objects.filter(recipient=recipient).exists()
        assert not _email_rows().exists()


class TestNullSubscriptionDedup:
    """Port-level + DB-level proof of the NULL-subscription dedup fix."""

    def _notification(self, user_factory):
        recipient, actor = user_factory(), user_factory()
        return Notification.objects.create(
            recipient=recipient,
            actor=actor,
            notification_type=Notification.NotificationType.MENTION,
            verb="mentioned you",
        )

    def test_record_is_idempotent_for_null_subscription(self, user_factory):
        """Port contract on BOTH backends: the second record() for
        (notification, email, NULL) returns the same row, created=False."""
        notification = self._notification(user_factory)
        ledger = get_push_delivery_provider().delivery_ledger()

        first = ledger.record(notification_id=notification.id, channel="email")
        second = ledger.record(notification_id=notification.id, channel="email")

        assert first.created is True
        assert second.created is False
        assert second.record.id == first.record.id
        assert _email_rows(notification).count() == 1

    def test_db_constraint_rejects_duplicate_null_subscription_row(self, user_factory):
        """The conditional unique constraint is enforced at the DB — a raw
        duplicate insert (bypassing get_or_create) is rejected. This is the
        guarantee the base (notification, channel, subscription) constraint
        could not give NULL-subscription rows (SQL NULLS-DISTINCT semantics)."""
        notification = self._notification(user_factory)
        NotificationDelivery.objects.create(
            notification=notification,
            channel=NotificationDelivery.Channel.EMAIL,
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationDelivery.Channel.EMAIL,
            )

    def test_distinct_subscription_rows_remain_allowed(self, user_factory):
        """The new constraint must not over-constrain: web_push rows with
        DIFFERENT subscriptions for the same notification stay legal."""
        from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash
        from infrastructure.persistence.notifications.models import PushSubscription

        notification = self._notification(user_factory)
        for suffix in ("a", "b"):
            endpoint = f"https://push.example.com/send/dedup-{suffix}"
            subscription = PushSubscription.objects.create(
                user=notification.recipient,
                endpoint=endpoint,
                endpoint_hash=derive_endpoint_hash(endpoint),
                keys={"p256dh": "BPubKey", "auth": "authsecret"},
            )
            NotificationDelivery.objects.create(
                notification=notification,
                subscription=subscription,
                channel=NotificationDelivery.Channel.WEB_PUSH,
            )

        assert (
            NotificationDelivery.objects.filter(
                notification=notification,
                channel=NotificationDelivery.Channel.WEB_PUSH,
            ).count()
            == 2
        )

"""Behaviour tests for the T1-S6 web-push sender task.

Test design (testing skill): enter through the task (the use-case entry
point), stub ONLY the external HTTP boundary (one fake for the
``WebPushSenderPort``, injected via a provider override on
``push_delivery_provider._default``), and use the REAL internal driven
adapters — the ORM ledger and subscription registry — against the test DB.

Covers: flag-off truthful skip, the sent path + exact payload shape
(including the absolutized deep link), 404/410 device expiry, transient
failure + Celery retry semantics, mixed-batch per-row isolation, and
re-run idempotency (sent rows never re-sent; failed rows re-claimed).
"""

from __future__ import annotations

import json

import pytest
from celery.exceptions import Retry

from components.notifications.application.ports.web_push_sender_port import (
    SubscriptionGoneError,
    TransientPushError,
    WebPushSenderPort,
)
from components.notifications.application.providers import push_delivery_provider
from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash
from components.notifications.infrastructure.tasks.web_push_tasks import (
    SUBSCRIPTION_GONE_REASON,
    SUBSCRIPTION_UNAVAILABLE_REASON,
    WEB_PUSH_SENDER_DISABLED_REASON,
    WEB_PUSH_TTL_SECONDS,
    deliver_web_push,
)
from infrastructure.persistence.notifications.models import (
    Notification,
    NotificationDelivery,
    PushSubscription,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

ENDPOINT = "https://push.example.com/send/task-device"


class FakeWebPushSender(WebPushSenderPort):
    """One fake for the sender port — scriptable outcome per endpoint."""

    def __init__(self):
        self.sent: list[dict] = []
        self.outcomes: dict[str, Exception] = {}

    def fail_endpoint(self, endpoint: str, exc: Exception) -> None:
        self.outcomes[endpoint] = exc

    def send(self, *, subscription_info, payload, ttl):
        outcome = self.outcomes.get(subscription_info["endpoint"])
        if outcome is not None:
            raise outcome
        self.sent.append({"subscription_info": subscription_info, "payload": payload, "ttl": ttl})


@pytest.fixture
def fake_sender(monkeypatch):
    """Inject the fake sender through the provider composition root."""
    sender = FakeWebPushSender()
    monkeypatch.setattr(push_delivery_provider._default, "web_push_sender", lambda: sender)
    return sender


@pytest.fixture
def push_enabled(settings):
    settings.WEB_PUSH_ENABLED = True
    settings.WEBPUSH_VAPID_PRIVATE_KEY = "test-private-key"
    settings.WEBPUSH_VAPID_ADMIN_EMAIL = "ops@example.org"
    settings.FRONTEND_URL = "https://app.example.org"
    return settings


def _subscribe(user, suffix=""):
    endpoint = f"{ENDPOINT}{suffix}"
    return PushSubscription.objects.create(
        user=user,
        endpoint=endpoint,
        endpoint_hash=derive_endpoint_hash(endpoint),
        keys={"p256dh": "BPubKey", "auth": "authsecret"},
    )


def _notification(recipient, actor, workspace=None, **overrides):
    fields = {
        "recipient": recipient,
        "actor": actor,
        "notification_type": Notification.NotificationType.MENTION,
        "verb": "mentioned you",
        "workspace": workspace,
    }
    fields.update(overrides)
    return Notification.objects.create(**fields)


def _record(notification, subscription):
    return NotificationDelivery.objects.create(
        notification=notification,
        subscription=subscription,
        channel=NotificationDelivery.Channel.WEB_PUSH,
    )


def _run(notification):
    return deliver_web_push.apply(kwargs={"notification_id": notification.id})


class TestFlagOff:
    def test_flag_off_skips_without_sending(self, user_factory, fake_sender, settings):
        settings.WEB_PUSH_ENABLED = False
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification, _subscribe(recipient))

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == WEB_PUSH_SENDER_DISABLED_REASON
        assert delivery.attempts == 0  # nothing was attempted
        assert fake_sender.sent == []

    def test_flag_on_without_private_key_skips(self, user_factory, fake_sender, settings):
        settings.WEB_PUSH_ENABLED = True
        settings.WEBPUSH_VAPID_PRIVATE_KEY = ""
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification, _subscribe(recipient))

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == WEB_PUSH_SENDER_DISABLED_REASON
        assert fake_sender.sent == []


class TestSentPath:
    def test_success_marks_sent_and_increments_attempts(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification, _subscribe(recipient))

        result = _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 1
        assert delivery.last_error == ""
        assert result.get() == {
            "notification_id": str(notification.id),
            "sent": 1,
            "failed": 0,
            "skipped": 0,
        }

    def test_payload_shape_and_absolutized_link(self, user_factory, workspace_factory, fake_sender, push_enabled):
        actor = user_factory()
        actor.first_name, actor.last_name = "Amara", "Okoye"
        actor.save(update_fields=["first_name", "last_name"])
        recipient = user_factory()
        workspace = workspace_factory()
        notification = _notification(
            recipient,
            actor,
            workspace=workspace,
            metadata={"link": f"/w/{workspace.id}/dashboard"},
            logo_url="https://cdn.example.org/logo.png",
        )
        subscription = _subscribe(recipient)
        _record(notification, subscription)

        _run(notification)

        assert len(fake_sender.sent) == 1
        send = fake_sender.sent[0]
        assert send["subscription_info"] == {
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": "BPubKey", "auth": "authsecret"},
        }
        assert send["ttl"] == WEB_PUSH_TTL_SECONDS
        payload = json.loads(send["payload"])
        assert payload == {
            "title": workspace.workspace_name,
            "body": "Amara Okoye mentioned you",
            "link": f"https://app.example.org/w/{workspace.id}/dashboard",
            "notification_id": str(notification.id),
            "icon": "https://cdn.example.org/logo.png",
        }

    def test_payload_without_workspace_or_link(self, user_factory, fake_sender, push_enabled):
        actor = user_factory()  # no first/last name → username in body
        recipient = user_factory()
        notification = _notification(recipient, actor)
        _record(notification, _subscribe(recipient))

        _run(notification)

        payload = json.loads(fake_sender.sent[0]["payload"])
        assert payload["title"] == "New notification"
        assert payload["body"] == f"{actor.username} mentioned you"
        assert payload["link"] is None
        assert "icon" not in payload


class TestSubscriptionGone:
    def test_410_expires_device_and_terminates_row(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        subscription = _subscribe(recipient)
        delivery = _record(notification, subscription)
        fake_sender.fail_endpoint(subscription.endpoint, SubscriptionGoneError("410"))

        _run(notification)

        subscription.refresh_from_db()
        assert subscription.status == PushSubscription.Status.EXPIRED
        delivery.refresh_from_db()
        # Terminal no-retry outcome — skipped per the ledger port contract
        # ("device expired"); failed would be re-claimed by the retry.
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == SUBSCRIPTION_GONE_REASON
        assert delivery.attempts == 1  # a send WAS attempted

    def test_gone_row_is_not_retried_on_rerun(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        subscription = _subscribe(recipient)
        delivery = _record(notification, subscription)
        fake_sender.fail_endpoint(subscription.endpoint, SubscriptionGoneError("410"))

        _run(notification)
        _run(notification)

        delivery.refresh_from_db()
        assert delivery.attempts == 1  # second run claimed nothing


class TestTransientFailure:
    def test_transient_marks_failed_and_raises_for_retry(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        subscription = _subscribe(recipient)
        delivery = _record(notification, subscription)
        fake_sender.fail_endpoint(subscription.endpoint, TransientPushError("push service 503"))

        # Eager Celery propagates the Retry the task raised — the task
        # signalled "re-deliver later" instead of reporting success.
        with pytest.raises(Retry):
            _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.FAILED
        assert "503" in delivery.last_error
        assert delivery.attempts == 1

    def test_retry_reclaims_failed_row_then_sends(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        subscription = _subscribe(recipient)
        delivery = _record(notification, subscription)
        fake_sender.fail_endpoint(subscription.endpoint, TransientPushError("push service 503"))

        with pytest.raises(Retry):
            _run(notification)
        delivery.refresh_from_db()
        first_attempts = delivery.attempts
        assert delivery.status == NotificationDelivery.Status.FAILED

        # Push service recovered — the (simulated) Celery retry re-claims
        # the failed row and delivers it.
        fake_sender.outcomes.clear()
        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == first_attempts + 1


class TestBatchIsolation:
    def test_one_dead_device_does_not_block_the_others(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        ok = _subscribe(recipient, suffix="-ok")
        gone = _subscribe(recipient, suffix="-gone")
        flaky = _subscribe(recipient, suffix="-flaky")
        deliveries = {sub.id: _record(notification, sub) for sub in (ok, gone, flaky)}
        fake_sender.fail_endpoint(gone.endpoint, SubscriptionGoneError("410"))
        fake_sender.fail_endpoint(flaky.endpoint, TransientPushError("timeout"))

        with pytest.raises(Retry):  # the transient row makes the task ask for a retry
            _run(notification)

        deliveries[ok.id].refresh_from_db()
        deliveries[gone.id].refresh_from_db()
        deliveries[flaky.id].refresh_from_db()
        assert deliveries[ok.id].status == NotificationDelivery.Status.SENT
        assert deliveries[gone.id].status == NotificationDelivery.Status.SKIPPED
        assert deliveries[flaky.id].status == NotificationDelivery.Status.FAILED
        assert len(fake_sender.sent) == 1

    def test_unexpected_error_is_isolated_and_row_failed(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        broken = _subscribe(recipient, suffix="-broken")
        ok = _subscribe(recipient, suffix="-ok2")
        broken_delivery = _record(notification, broken)
        ok_delivery = _record(notification, ok)
        fake_sender.fail_endpoint(broken.endpoint, ValueError("unexpected bug"))

        _run(notification)

        broken_delivery.refresh_from_db()
        ok_delivery.refresh_from_db()
        assert broken_delivery.status == NotificationDelivery.Status.FAILED
        assert ok_delivery.status == NotificationDelivery.Status.SENT


class TestIdempotency:
    def test_rerun_leaves_sent_rows_untouched(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification, _subscribe(recipient))

        _run(notification)
        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 1
        assert len(fake_sender.sent) == 1  # never double-sent

    def test_inactive_subscription_row_is_skipped_without_send(self, user_factory, fake_sender, push_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        subscription = _subscribe(recipient)
        delivery = _record(notification, subscription)
        subscription.status = PushSubscription.Status.REVOKED
        subscription.save(update_fields=["status"])

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == SUBSCRIPTION_UNAVAILABLE_REASON
        assert delivery.attempts == 0
        assert fake_sender.sent == []

    def test_unknown_notification_id_is_a_noop(self, fake_sender, push_enabled):
        unknown = 987654  # Notification pk is an AutoField int
        result = deliver_web_push.apply(kwargs={"notification_id": unknown})

        assert result.get() == {"notification_id": str(unknown), "sent": 0, "failed": 0, "skipped": 0}
        assert fake_sender.sent == []

    def test_notification_deleted_midflight_skips_rows(self, user_factory, fake_sender, push_enabled, monkeypatch):
        """Deleting the notification CASCADEs its ledger rows, so the
        payload-builder-returns-None branch only fires in the narrow race
        between the deliverable fetch and the payload read — simulated by
        stubbing the builder."""
        from components.notifications.infrastructure.tasks import web_push_tasks
        from components.notifications.infrastructure.tasks.web_push_tasks import NOTIFICATION_MISSING_REASON

        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification, _subscribe(recipient))
        monkeypatch.setattr(web_push_tasks, "_build_web_push_payload", lambda notification_id: None)

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == NOTIFICATION_MISSING_REASON
        assert fake_sender.sent == []


class TestEndToEndDispatch:
    def test_dispatch_funnel_delivers_through_fake_sender(self, user_factory, fake_sender, push_enabled):
        """Full path: dispatch → channel gate → ledger record → eager
        deliver_web_push → fake sender → ledger row sent."""
        from components.notifications.infrastructure.adapters.notification_service import (
            invalidate_channel_cache,
        )
        from components.notifications.workers.tasks import dispatch_notification_async
        from infrastructure.persistence.notifications.userpreferences.models import UserPreference

        recipient, actor = user_factory(), user_factory()
        pref, _ = UserPreference.objects.get_or_create(user=recipient)
        pref.push_notifications = True
        pref.save(update_fields=["push_notifications"])
        invalidate_channel_cache(recipient.pk)
        subscription = _subscribe(recipient)

        dispatch_notification_async.apply(
            kwargs={
                "recipient_id": str(recipient.pk),
                "actor_id": str(actor.pk),
                "verb": "mentioned you",
                "notification_type": Notification.NotificationType.MENTION,
            }
        )

        notification = Notification.objects.get(recipient=recipient)
        delivery = NotificationDelivery.objects.get(notification=notification)
        assert delivery.subscription_id == subscription.id
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 1
        assert len(fake_sender.sent) == 1
        payload = json.loads(fake_sender.sent[0]["payload"])
        assert payload["notification_id"] == str(notification.id)
        assert payload["body"].endswith("mentioned you")

"""Integration tests for the T1-S8 email sender against real ledger rows.

Covers the flag-off truthful skip, the enabled path (sent), transient
failure + Celery retry semantics, the no-email-address skip, and idempotent
re-runs. The email boundary is a fake adapter injected through the shared
``email_adapter_provider`` composition root (HTTP/SMTP is stubbed at the
port; the ledger + notification rows are real DB I/O).
"""

from __future__ import annotations

import pytest
from celery.exceptions import Retry

from components.notifications.infrastructure.tasks.email_tasks import (
    EMAIL_CHANNEL_DISABLED_REASON,
    EMAIL_SEND_FAILED_ERROR,
    NOTIFICATION_EMAIL_TEMPLATE,
    NOTIFICATION_MISSING_REASON,
    RECIPIENT_EMAIL_MISSING_REASON,
    deliver_email,
)
from components.shared_platform.application.providers import email_adapter_provider
from infrastructure.persistence.notifications.models import Notification, NotificationDelivery

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class FakeEmailAdapter:
    """One fake for the EmailSendingPort — records sends, scripted outcome."""

    def __init__(self):
        self.sent = []
        self.result = True
        self.raise_exc = None

    def send_templated(self, *, to, subject, template, context, from_email="", workspace_id=None):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.sent.append(
            {
                "to": list(to),
                "subject": subject,
                "template": template,
                "context": context,
                "workspace_id": workspace_id,
            }
        )
        return self.result


class _FakeProvider:
    def __init__(self, adapter):
        self._adapter = adapter

    def adapter(self):
        return self._adapter


@pytest.fixture
def fake_email(monkeypatch):
    """Inject the fake adapter through the shared provider composition root."""
    adapter = FakeEmailAdapter()
    monkeypatch.setattr(email_adapter_provider, "_default", _FakeProvider(adapter))
    return adapter


@pytest.fixture
def email_enabled(settings):
    settings.NOTIF_EMAIL_CHANNEL_ENABLED = True
    settings.FRONTEND_URL = "https://app.example.org"
    return settings


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


def _record(notification):
    return NotificationDelivery.objects.create(
        notification=notification,
        channel=NotificationDelivery.Channel.EMAIL,
    )


def _run(notification):
    return deliver_email.apply(kwargs={"notification_id": notification.id})


class TestFlagOff:
    def test_flag_off_skips_without_sending(self, user_factory, fake_email, settings):
        settings.NOTIF_EMAIL_CHANNEL_ENABLED = False
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification)

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == EMAIL_CHANNEL_DISABLED_REASON
        assert fake_email.sent == []


class TestEnabledPath:
    def test_sends_through_shared_email_layer_and_marks_sent(self, user_factory, fake_email, email_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(
            recipient,
            actor,
            metadata={"link": "/notifications/inbox"},
        )
        delivery = _record(notification)

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 1
        assert len(fake_email.sent) == 1
        sent = fake_email.sent[0]
        assert sent["to"] == [recipient.email]
        assert sent["template"] == NOTIFICATION_EMAIL_TEMPLATE
        assert sent["context"]["verb"] == "mentioned you"
        assert sent["context"]["link_url"] == "https://app.example.org/notifications/inbox"

    def test_unknown_notification_id_is_a_noop(self, fake_email, email_enabled):
        unknown = 987654  # Notification pk is an AutoField int
        result = deliver_email.apply(kwargs={"notification_id": unknown})

        assert result.get() == {"notification_id": str(unknown), "sent": 0, "failed": 0, "skipped": 0}
        assert fake_email.sent == []

    def test_notification_deleted_midflight_skips_rows(self, user_factory, fake_email, email_enabled, monkeypatch):
        """Deleting the notification CASCADEs its ledger rows, so the
        loader-returns-None branch only fires in the narrow race between
        the deliverable fetch and the row read — simulated by stubbing the
        loader (same pattern as the web_push twin test)."""
        from components.notifications.infrastructure.tasks import email_tasks

        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification)
        monkeypatch.setattr(email_tasks, "_load_notification", lambda notification_id: None)

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == NOTIFICATION_MISSING_REASON
        assert fake_email.sent == []

    def test_recipient_without_email_skips(self, user_factory, fake_email, email_enabled):
        recipient, actor = user_factory(), user_factory()
        type(recipient).objects.filter(pk=recipient.pk).update(email="")
        notification = _notification(recipient, actor)
        delivery = _record(notification)

        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED
        assert delivery.last_error == RECIPIENT_EMAIL_MISSING_REASON
        assert fake_email.sent == []


class TestFailureAndRetry:
    def test_backend_failure_marks_failed_and_raises_for_retry(self, user_factory, fake_email, email_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification)
        fake_email.result = False  # shared adapter sends fail-silently → False

        with pytest.raises(Retry):
            deliver_email.apply(kwargs={"notification_id": notification.id}, throw=True)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.FAILED
        assert delivery.last_error == EMAIL_SEND_FAILED_ERROR
        assert delivery.attempts == 1

    def test_retry_reclaims_failed_row_then_sends(self, user_factory, fake_email, email_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification)
        fake_email.result = False

        with pytest.raises(Retry):
            deliver_email.apply(kwargs={"notification_id": notification.id}, throw=True)

        # Backend recovered — the (simulated) Celery retry re-claims the
        # failed row and completes the send.
        fake_email.result = True
        _run(notification)

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 2

    def test_unexpected_exception_marks_failed_without_retry(self, user_factory, fake_email, email_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification)
        fake_email.raise_exc = ValueError("template context bug")

        result = _run(notification)

        # Completes without asking for a retry — a deterministic bug is not transient.
        assert result.get()["failed"] == 1
        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.FAILED


class TestIdempotentRerun:
    def test_rerun_after_sent_sends_nothing(self, user_factory, fake_email, email_enabled):
        recipient, actor = user_factory(), user_factory()
        notification = _notification(recipient, actor)
        delivery = _record(notification)

        _run(notification)
        _run(notification)  # duplicate enqueue / operator re-run

        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SENT
        assert delivery.attempts == 1
        assert len(fake_email.sent) == 1

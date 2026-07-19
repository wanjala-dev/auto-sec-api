"""T1-S9 emitter #1 — DMs raise MESSAGE notifications through the funnel.

Enters through ``SendMessageUseCase`` (the provider-built one — real
repos, real adapter). Celery is eager under test settings;
``django_capture_on_commit_callbacks(execute=True)`` flushes the
dispatcher's post-commit hop.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

from components.messaging.application.providers.messaging_provider import make_send_message
from infrastructure.persistence.messaging.models import Conversation, ConversationParticipant
from infrastructure.persistence.notifications.models import Notification

pytestmark = pytest.mark.django_db


def _conversation(*, workspace=None, participants=()):
    conversation = Conversation.objects.create(
        conversation_type=Conversation.WORKSPACE if workspace else Conversation.PRIVATE,
        workspace=workspace,
    )
    for user, muted in participants:
        ConversationParticipant.objects.create(conversation=conversation, user=user, is_muted=muted)
    return conversation


def _send(django_capture_on_commit_callbacks, *, conversation, sender, body="hello there", metadata=None):
    with django_capture_on_commit_callbacks(execute=True):
        return make_send_message().execute(
            conversation_id=conversation.id,
            sender_id=sender.id,
            body=body,
            metadata=metadata,
        )


class TestMessageNotification:
    def test_recipient_gets_message_notification_with_link(
        self, user_factory, workspace_factory, django_capture_on_commit_callbacks
    ):
        sender = user_factory(username="dm-sender", email="dm-sender@example.com")
        recipient = user_factory(username="dm-recipient", email="dm-recipient@example.com")
        workspace = workspace_factory(owner=sender)
        conversation = _conversation(workspace=workspace, participants=[(sender, False), (recipient, False)])

        _send(django_capture_on_commit_callbacks, conversation=conversation, sender=sender)

        row = Notification.objects.get(recipient=recipient)
        assert row.notification_type == Notification.NotificationType.MESSAGE
        assert row.actor == sender
        assert row.verb == "sent you a message"
        assert row.metadata["conversation_id"] == str(conversation.id)
        assert row.metadata["preview"] == "hello there"
        assert row.metadata["link"] == f"/w/{workspace.pk}/messages"
        # The sender never hears about their own message.
        assert not Notification.objects.filter(recipient=sender).exists()

    def test_burst_in_same_conversation_dedups_to_one_row(
        self, user_factory, workspace_factory, django_capture_on_commit_callbacks
    ):
        sender = user_factory(username="burst-sender", email="burst-sender@example.com")
        recipient = user_factory(username="burst-recipient", email="burst-recipient@example.com")
        workspace = workspace_factory(owner=sender)
        conversation = _conversation(workspace=workspace, participants=[(sender, False), (recipient, False)])

        _send(django_capture_on_commit_callbacks, conversation=conversation, sender=sender, body="one")
        _send(django_capture_on_commit_callbacks, conversation=conversation, sender=sender, body="two")

        assert Notification.objects.filter(recipient=recipient).count() == 1

    def test_muted_participant_is_not_notified(
        self, user_factory, workspace_factory, django_capture_on_commit_callbacks
    ):
        sender = user_factory(username="mute-sender", email="mute-sender@example.com")
        muted = user_factory(username="muted-user", email="muted-user@example.com")
        listening = user_factory(username="listening-user", email="listening-user@example.com")
        workspace = workspace_factory(owner=sender)
        conversation = _conversation(
            workspace=workspace,
            participants=[(sender, False), (muted, True), (listening, False)],
        )

        _send(django_capture_on_commit_callbacks, conversation=conversation, sender=sender)

        assert not Notification.objects.filter(recipient=muted).exists()
        assert Notification.objects.filter(recipient=listening).count() == 1

    def test_preference_disabled_recipient_is_not_notified(
        self, user_factory, workspace_factory, django_capture_on_commit_callbacks
    ):
        sender = user_factory(username="pref-sender", email="pref-sender@example.com")
        recipient = user_factory(username="pref-off", email="pref-off@example.com")
        workspace = workspace_factory(owner=sender)
        conversation = _conversation(workspace=workspace, participants=[(sender, False), (recipient, False)])

        UserPreference = django_apps.get_model("userpreferences", "UserPreference")
        pref, _ = UserPreference.objects.get_or_create(user=recipient)
        pref.notifications_enabled = False
        pref.save(update_fields=["notifications_enabled"])

        _send(django_capture_on_commit_callbacks, conversation=conversation, sender=sender)

        assert not Notification.objects.filter(recipient=recipient).exists()

    def test_share_card_message_notifies_via_share_leg_not_message_leg(
        self, user_factory, workspace_factory, django_capture_on_commit_callbacks
    ):
        """A share-card send raises ONE share notification, no MESSAGE row.

        Also locks in the fix for the missing ``NotificationDispatcher``
        import in ``ShareNotificationAdapter`` — before it, every share
        dispatch died with a swallowed ``NameError`` and no row ever landed.
        """
        sender = user_factory(username="share-sender", email="share-sender@example.com")
        recipient = user_factory(username="share-recipient", email="share-recipient@example.com")
        workspace = workspace_factory(owner=sender)
        conversation = _conversation(workspace=workspace, participants=[(sender, False), (recipient, False)])

        _send(
            django_capture_on_commit_callbacks,
            conversation=conversation,
            sender=sender,
            body="check this out",
            metadata={"share": {"kind": "report", "title": "Q1 report", "url": "/w/x/reports", "excerpt": ""}},
        )

        rows = Notification.objects.filter(recipient=recipient)
        assert rows.count() == 1
        assert rows.first().notification_type == "share"

    def test_private_conversation_still_notifies_without_workspace(
        self, user_factory, django_capture_on_commit_callbacks
    ):
        sender = user_factory(username="priv-sender", email="priv-sender@example.com")
        recipient = user_factory(username="priv-recipient", email="priv-recipient@example.com")
        conversation = _conversation(participants=[(sender, False), (recipient, False)])

        _send(django_capture_on_commit_callbacks, conversation=conversation, sender=sender)

        row = Notification.objects.get(recipient=recipient)
        assert row.notification_type == Notification.NotificationType.MESSAGE
        assert row.workspace is None

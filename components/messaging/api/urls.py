"""URL configuration for the messaging bounded context.

Mounted at ``/messaging/`` in the root URL configuration.
"""

from django.urls import path

from components.messaging.api.controller import (
    ConversationArchiveController,
    ConversationListController,
    ConversationMuteController,
    ConversationStarController,
    ConversationStartController,
    MarkReadController,
    MessageDeleteController,
    MessageListController,
    MessageSendController,
    UnreadCountController,
)

urlpatterns = [
    # ── Conversations ────────────────────────────────────────────
    path(
        "conversations/",
        ConversationListController.as_view(),
        name="messaging-conversation-list",
    ),
    path(
        "conversations/start/",
        ConversationStartController.as_view(),
        name="messaging-conversation-start",
    ),
    # ── Conversation management ──────────────────────────────────
    path(
        "conversations/<uuid:conversation_id>/archive/",
        ConversationArchiveController.as_view(),
        name="messaging-conversation-archive",
        kwargs={"action": "archive"},
    ),
    path(
        "conversations/<uuid:conversation_id>/unarchive/",
        ConversationArchiveController.as_view(),
        name="messaging-conversation-unarchive",
        kwargs={"action": "unarchive"},
    ),
    path(
        "conversations/<uuid:conversation_id>/star/",
        ConversationStarController.as_view(),
        name="messaging-conversation-star",
        kwargs={"action": "star"},
    ),
    path(
        "conversations/<uuid:conversation_id>/unstar/",
        ConversationStarController.as_view(),
        name="messaging-conversation-unstar",
        kwargs={"action": "unstar"},
    ),
    path(
        "conversations/<uuid:conversation_id>/mute/",
        ConversationMuteController.as_view(),
        name="messaging-conversation-mute",
        kwargs={"action": "mute"},
    ),
    path(
        "conversations/<uuid:conversation_id>/unmute/",
        ConversationMuteController.as_view(),
        name="messaging-conversation-unmute",
        kwargs={"action": "unmute"},
    ),
    # ── Messages ─────────────────────────────────────────────────
    path(
        "conversations/<uuid:conversation_id>/messages/",
        MessageListController.as_view(),
        name="messaging-message-list",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/send/",
        MessageSendController.as_view(),
        name="messaging-message-send",
    ),
    path(
        "messages/<uuid:message_id>/",
        MessageDeleteController.as_view(),
        name="messaging-message-delete",
    ),
    # ── Read receipts ────────────────────────────────────────────
    path(
        "conversations/<uuid:conversation_id>/read/",
        MarkReadController.as_view(),
        name="messaging-mark-read",
    ),
    path(
        "unread/",
        UnreadCountController.as_view(),
        name="messaging-unread-counts",
    ),
]

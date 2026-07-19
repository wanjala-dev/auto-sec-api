"""ORM models for the messaging bounded context.

Key design decisions vs. the old ThreadModel/MessageModel:

1. **Per-participant state** — archive, star, mute, and last-read timestamps
   live on ``ConversationParticipant``, not on the conversation itself.
   Archiving a conversation no longer hides it for the other person.

2. **Symmetrical uniqueness** — ``ConversationParticipant`` uses a
   ``UniqueConstraint(conversation, user)`` to prevent duplicates.
   A single conversation record exists per pair; both users are
   participants.  ``find_private_between`` queries participants,
   not user/receiver columns.

3. **Soft-delete on messages** — messages are never hard-deleted.
   ``is_deleted`` + ``deleted_at`` preserve audit trails.

4. **TextField for body** — no more 1000-char limit.

5. **UUIDs everywhere** — consistent with the rest of the codebase.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    """A messaging channel between two or more participants."""

    PRIVATE = "private"
    WORKSPACE = "workspace"
    TYPE_CHOICES = [
        (PRIVATE, "Private"),
        (WORKSPACE, "Workspace"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=PRIVATE)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "messaging"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation {self.id} ({self.conversation_type})"


class ConversationParticipant(models.Model):
    """Per-user state within a conversation.

    Each user in a conversation gets their own participant record.
    This allows independent archiving, starring, muting, and
    read-tracking.
    """

    OWNER = "owner"
    MEMBER = "member"
    ROLE_CHOICES = [
        (OWNER, "Owner"),
        (MEMBER, "Member"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_participations",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=MEMBER)

    # Per-participant state
    is_archived = models.BooleanField(default=False)
    is_starred = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    last_read_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    archived_at = models.DateTimeField(null=True, blank=True)
    starred_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "messaging"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="unique_conversation_participant",
            ),
        ]
        ordering = ["-joined_at"]

    def __str__(self):
        return f"Participant {self.user_id} in {self.conversation_id}"


class Message(models.Model):
    """An individual message within a conversation."""

    TEXT = "text"
    IMAGE = "image"
    SYSTEM = "system"
    TYPE_CHOICES = [
        (TEXT, "Text"),
        (IMAGE, "Image"),
        (SYSTEM, "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_direct_messages",
    )
    body = models.TextField(blank=True, default="")
    message_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TEXT)
    image = models.ImageField(upload_to="uploads/message_photos/", blank=True, null=True)
    # Structured payload for rich message cards (task #21 — Share in chat).
    # {"share": {"kind", "title", "url", "excerpt"}} renders the shared
    # entity as a card in the chat instead of a bare link line. Additive:
    # plain messages carry {}.
    metadata = models.JSONField(default=dict, blank=True)

    # Soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "messaging"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["conversation", "created_at"],
                name="idx_msg_conv_created",
            ),
        ]

    def __str__(self):
        preview = (self.body[:40] + "...") if len(self.body) > 40 else self.body
        return f"Message {self.id}: {preview}"


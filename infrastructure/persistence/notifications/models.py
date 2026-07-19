from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from components.notifications.infrastructure.adapters.cache import invalidate_unread_count_cache
from infrastructure.persistence.users.models import CustomUser


class NotificationQuerySet(models.QuerySet):
    """Default queryset excludes archived notifications.

    Use ``.include_archived()`` or ``.archived()`` to access them.
    """

    def active(self):
        return self.filter(is_archived=False)

    def for_user(self, user):
        if user is None:
            return self.none()
        return self.active().filter(recipient=user)

    def unread(self):
        return self.active().filter(is_read=False)

    def read(self):
        return self.active().filter(is_read=True)

    def recent(self):
        return self.active().order_by("-created_at")

    def archived(self):
        return self.filter(is_archived=True)

    def include_archived(self):
        """Return the full queryset without filtering out archived rows."""
        return self.all()


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        LIKE = "like", "Like"
        COMMENT = "comment", "Comment"
        FOLLOW = "follow", "Follow"
        MENTION = "mention", "Mention"
        MESSAGE = "message", "Message"
        SYSTEM = "system", "System"
        AI_EVENT = "ai_event", "AI Event"
        REPORT = "report", "Report"

    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="received_notifications")
    actor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="sent_notifications")
    notification_type = models.CharField(max_length=32, choices=NotificationType.choices)
    verb = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    logo_url = models.URLField(blank=True, null=True)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Stored as text to support both integer and UUID targets.",
    )
    content_object = GenericForeignKey("content_type", "object_id")

    is_read = models.BooleanField(default=False)
    is_archived = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Soft-deleted by the archival task. Hidden from feeds but retained in DB.",
    )
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["recipient", "is_read"]),
            models.Index(fields=["recipient", "is_archived", "-created_at"]),
            models.Index(fields=["notification_type"]),
            models.Index(fields=["workspace"]),
            models.Index(fields=["recipient", "workspace"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.actor} {self.verb}"

    def mark_as_read(self, commit: bool = True) -> Notification:
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            if commit:
                self.save(update_fields=["is_read", "read_at", "updated_at"])
        return self

    def mark_as_unread(self, commit: bool = True) -> Notification:
        if self.is_read:
            self.is_read = False
            self.read_at = None
            if commit:
                self.save(update_fields=["is_read", "read_at", "updated_at"])
        return self

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        invalidate_unread_count_cache(self.recipient_id, self.workspace_id)

    def delete(self, *args, **kwargs):
        recipient_id = self.recipient_id
        workspace_id = self.workspace_id
        super().delete(*args, **kwargs)
        invalidate_unread_count_cache(recipient_id, workspace_id)

    # Backwards-compatibility helpers for templates/legacy callers -----------------
    # The `social` bounded context (Post/Comment/ThreadModel) was dropped in the
    # auto-sec fork; these shims now always return None.
    @property
    def post(self):
        return None

    @property
    def comment(self):
        return None

    @property
    def thread(self):
        return None

    # Legacy attribute shims ------------------------------------------------------
    @property
    def from_user(self):
        return self.actor

    @property
    def to_user(self):
        return self.recipient

    @property
    def date(self):
        return self.created_at

    @property
    def user_has_seen(self):
        return self.is_read


class WorkspaceNotificationPreference(models.Model):
    """Per-user toggle for receiving notifications scoped to a specific workspace."""

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="workspace_notification_preferences",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "workspace")
        indexes = [
            models.Index(fields=["user", "workspace"]),
            models.Index(fields=["workspace"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return f"{self.user_id}:{self.workspace_id} -> {self.is_enabled}"


class AINotificationPreference(models.Model):
    """Fine-grained per-channel AI notification toggle."""

    CHANNEL_GENERAL = "general"
    CHANNEL_TEAMMATE_STATUS = "teammate_status"
    CHANNEL_ACTION_CREATED = "action_created"
    CHANNEL_ACTION_AUTO_EXECUTED = "action_auto_executed"
    CHANNEL_ACTION_ERROR = "action_error"
    CHANNEL_REPORT_GENERATED = "report_generated"

    CHANNEL_CHOICES = (
        (CHANNEL_GENERAL, "General AI activity"),
        (CHANNEL_TEAMMATE_STATUS, "Orchestrator status"),
        (CHANNEL_ACTION_CREATED, "AI action created"),
        (CHANNEL_ACTION_AUTO_EXECUTED, "AI action auto executed"),
        (CHANNEL_ACTION_ERROR, "AI action error"),
        (CHANNEL_REPORT_GENERATED, "AI report generated"),
    )

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="ai_notification_preferences",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ai_notification_preferences",
    )
    channel = models.CharField(
        max_length=64,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_GENERAL,
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "workspace", "channel")
        indexes = [
            models.Index(fields=["user", "workspace", "channel"]),
            models.Index(fields=["workspace", "channel"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        return f"{self.user_id}:{self.workspace_id}:{self.channel} -> {self.is_enabled}"

"""Canonical enums for the Notifications bounded context.

These are the single source of truth for notification types and channels.
The ORM model TextChoices must align with these, not the other way around.
"""

from __future__ import annotations

from enum import Enum


class NotificationType(str, Enum):
    LIKE = "like"
    COMMENT = "comment"
    FOLLOW = "follow"
    MENTION = "mention"
    MESSAGE = "message"
    SYSTEM = "system"
    AI_EVENT = "ai_event"
    REPORT = "report"


class AINotificationChannel(str, Enum):
    GENERAL = "general"
    TEAMMATE_STATUS = "teammate_status"
    ACTION_CREATED = "action_created"
    ACTION_AUTO_EXECUTED = "action_auto_executed"
    ACTION_ERROR = "action_error"
    REPORT_GENERATED = "report_generated"


class DeliveryChannel(str, Enum):
    """Delivery channels a notification can fan out to after row creation.

    Values align with ``NotificationDelivery.Channel`` TextChoices on the ORM
    model (this enum is the source of truth).
    """

    REALTIME = "realtime"
    WEB_PUSH = "web_push"
    EMAIL = "email"


class PushPlatform(str, Enum):
    """Platforms a push device can register from. Web is first; native
    iOS/Android reuse the same registry later."""

    WEB = "web"
    IOS = "ios"
    ANDROID = "android"


class TimePeriod(str, Enum):
    """Pre-defined time periods for notification filtering."""

    TODAY = "today"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"

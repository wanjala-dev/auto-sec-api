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


class TimePeriod(str, Enum):
    """Pre-defined time periods for notification filtering."""

    TODAY = "today"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"

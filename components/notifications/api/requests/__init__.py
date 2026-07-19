"""Request DTOs for notifications bounded context."""

from __future__ import annotations

from .notification import MarkNotificationReadRequest, MarkAllNotificationsReadRequest
from .workspace_preference import CreateWorkspaceNotificationPreferenceRequest, UpdateWorkspaceNotificationPreferenceRequest
from .ai_preference import CreateAINotificationPreferenceRequest, UpdateAINotificationPreferenceRequest
from .user_preference import CreateUserPreferenceRequest, UpdateUserPreferenceRequest

__all__ = [
    'MarkNotificationReadRequest',
    'MarkAllNotificationsReadRequest',
    'CreateWorkspaceNotificationPreferenceRequest',
    'UpdateWorkspaceNotificationPreferenceRequest',
    'CreateAINotificationPreferenceRequest',
    'UpdateAINotificationPreferenceRequest',
    'CreateUserPreferenceRequest',
    'UpdateUserPreferenceRequest',
]

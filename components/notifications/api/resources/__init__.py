"""Resource DTOs for notifications bounded context."""

from __future__ import annotations

from .notification import (
    NotificationResource,
    NotificationCollectionResource,
    UnreadCountResource,
    MarkAllReadResponse,
    UserSummary as NotificationUserSummary,
    WorkspaceSummary as NotificationWorkspaceSummary,
    TargetObject,
)
from .workspace_preference import (
    WorkspaceNotificationPreferenceResource,
    WorkspaceNotificationPreferenceCollectionResource,
    WorkspaceSummary as WorkspacePreferenceWorkspaceSummary,
)
from .ai_preference import (
    AINotificationPreferenceResource,
    AINotificationPreferenceCollectionResource,
    WorkspaceSummary as AIPreferenceWorkspaceSummary,
)
from .user_preference import (
    UserPreferenceResource,
    UserPreferenceCollectionResource,
)

__all__ = [
    'NotificationResource',
    'NotificationCollectionResource',
    'UnreadCountResource',
    'MarkAllReadResponse',
    'NotificationUserSummary',
    'NotificationWorkspaceSummary',
    'TargetObject',
    'WorkspaceNotificationPreferenceResource',
    'WorkspaceNotificationPreferenceCollectionResource',
    'WorkspacePreferenceWorkspaceSummary',
    'AINotificationPreferenceResource',
    'AINotificationPreferenceCollectionResource',
    'AIPreferenceWorkspaceSummary',
    'UserPreferenceResource',
    'UserPreferenceCollectionResource',
]

"""URL configuration for the notifications bounded context.

Provides endpoints for notifications, workspace/AI preferences, and user preferences.
Mounted at ``/notifications/`` in the root URL configuration.
User preferences are also mounted at ``/userpreferences/`` for backward compatibility.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from components.notifications.api.controller import (
    AINotificationPreferenceViewSet,
    NotificationViewSet,
    UserPreferenceDetailView,
    UserPreferenceView,
    WorkspaceNotificationPreferenceViewSet,
)

app_name = 'notifications'

router = SimpleRouter()
router.register(r'preferences/workspaces', WorkspaceNotificationPreferenceViewSet, basename='workspace-notification-preference')
router.register(r'preferences/ai', AINotificationPreferenceViewSet, basename='ai-notification-preference')
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),
    # User preferences (also accessible at /userpreferences/ via root urlconf)
    path('userpreferences/', UserPreferenceView.as_view(), name='userpreference-list'),
    path('userpreferences/<str:uuid>/', UserPreferenceDetailView.as_view(), name='userpreference-detail'),
]

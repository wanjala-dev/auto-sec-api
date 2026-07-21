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
    PushSubscriptionController,
    UserPreferenceDetailView,
    UserPreferenceView,
    VapidPublicKeyController,
    WorkspaceNotificationPreferenceViewSet,
)

app_name = "notifications"

router = SimpleRouter()
router.register(
    r"preferences/workspaces", WorkspaceNotificationPreferenceViewSet, basename="workspace-notification-preference"
)
router.register(r"preferences/ai", AINotificationPreferenceViewSet, basename="ai-notification-preference")
router.register(r"", NotificationViewSet, basename="notification")

urlpatterns = [
    # Push device registry (T1-S5) — before the router include so the
    # catch-all notification detail route can never shadow these paths.
    path("push/subscriptions/", PushSubscriptionController.as_view(), name="push-subscriptions"),
    path("push/vapid-public-key/", VapidPublicKeyController.as_view(), name="push-vapid-public-key"),
    path("", include(router.urls)),
    # User preferences (also accessible at /userpreferences/ via root urlconf)
    path("userpreferences/", UserPreferenceView.as_view(), name="userpreference-list"),
    path("userpreferences/<str:uuid>/", UserPreferenceDetailView.as_view(), name="userpreference-detail"),
]

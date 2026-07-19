"""Notifications bounded context controller.

All HTTP endpoints for notifications: listing, marking read, unread counts,
workspace/AI notification preferences, and user notification preferences.
"""

from __future__ import annotations

from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from components.notifications.application.providers.notifications_models_provider import (
    get_notifications_models_provider,
)
from components.notifications.application.service import NotificationsService
from components.notifications.mappers.rest.notification_serializers import (
    AINotificationPreferenceSerializer,
    NotificationSerializer,
    WorkspaceNotificationPreferenceSerializer,
)
from components.notifications.mappers.rest.user_preferences_serializers import (
    UserPreferenceSerializer,
)
from components.workspace.api.workspace_permissions import IsUnauthenticatedOrAdminOrStaff

# Module-level service instance
_notifications_service = NotificationsService()

# ── Notifications ────────────────────────────────────────────────────────


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """API surface for notification management.

    list + retrieve use ORM queryset (DRF pagination/serializer integration).
    mark_read / mark_all_read / unread_count delegate through the provider.
    """

    from components.notifications.api.pagination import NotificationCursorPagination

    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = NotificationCursorPagination
    lookup_field = "pk"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            Notification = get_notifications_models_provider().Notification
            return Notification.objects.none()

        queryset = _notifications_service.get_notifications_queryset(self.request.user.id)

        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            if is_read.lower() in ("1", "true", "yes"):
                queryset = queryset.filter(is_read=True)
            elif is_read.lower() in ("0", "false", "no"):
                queryset = queryset.filter(is_read=False)

        notification_type = self.request.query_params.get("type")
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        workspace_param = self._workspace_filter_value()
        if workspace_param:
            queryset = queryset.filter(workspace_id=workspace_param)

        queryset = self._apply_created_filters(queryset)
        return queryset.order_by("-created_at")

    # ----- helpers -----

    def _workspace_filter_value(self):
        raw = self.request.query_params.get("workspace")
        if not raw:
            return None
        try:
            return str(UUID(raw))
        except (TypeError, ValueError):
            return None

    def _apply_created_filters(self, queryset):
        from datetime import timedelta

        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        created_after = self._parse_datetime(
            self.request.query_params.get("created_after"), timezone, parse_datetime
        )
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)

        created_before = self._parse_datetime(
            self.request.query_params.get("created_before"), timezone, parse_datetime
        )
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)

        period = (self.request.query_params.get("period") or "").lower()
        if period:
            now = timezone.now()
            if period == "today":
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(created_at__gte=start)
            elif period == "last_7_days":
                queryset = queryset.filter(created_at__gte=now - timedelta(days=7))
            elif period == "last_30_days":
                queryset = queryset.filter(created_at__gte=now - timedelta(days=30))
        return queryset

    @staticmethod
    def _parse_datetime(value, timezone, parse_datetime):
        if not value:
            return None
        dt = parse_datetime(value)
        if dt is None:
            return None
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    # ----- actions delegated through provider -----

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark a single notification as read."""
        from components.notifications.application.commands.mark_notifications_command import (
            MarkNotificationReadCommand,
        )

        result = _notifications_service.mark_notification_read(
            MarkNotificationReadCommand(
                notification_id=int(pk),
                user_id=request.user.id,
            )
        )
        notification = self.get_object()
        serializer = self.get_serializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Mark all unread notifications as read."""
        from components.notifications.application.commands.mark_notifications_command import (
            MarkAllNotificationsReadCommand,
        )

        result = _notifications_service.mark_all_notifications_read(
            MarkAllNotificationsReadCommand(
                user_id=request.user.id,
                workspace_id=(
                    UUID(self._workspace_filter_value())
                    if self._workspace_filter_value()
                    else None
                ),
            )
        )
        return Response(
            {"updated": result.updated_count}, status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        """Return the unread notification count."""
        workspace_param = self._workspace_filter_value()
        count = _notifications_service.get_unread_count(
            request.user.id,
            workspace_id=UUID(workspace_param) if workspace_param else None,
        )
        return Response({"count": count})


# ── Workspace Notification Preferences ───────────────────────────────────


class WorkspaceNotificationPreferenceViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Workspace notification preferences — CRUD with notification side-effect."""

    serializer_class = WorkspaceNotificationPreferenceSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "workspace_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            WorkspaceNotificationPreference = get_notifications_models_provider().WorkspaceNotificationPreference
            return WorkspaceNotificationPreference.objects.none()
        return _notifications_service.get_workspace_preferences_queryset(self.request.user.id)

    def perform_create(self, serializer):
        preference = serializer.save(user=self.request.user)
        self._invalidate_pref_cache(preference)
        self._notify_preference_change(preference)

    def perform_update(self, serializer):
        preference = serializer.save(user=self.request.user)
        self._invalidate_pref_cache(preference)
        self._notify_preference_change(preference)

    @staticmethod
    def _invalidate_pref_cache(preference):
        from components.notifications.application.providers.notification_cache_provider import (
            get_notification_cache_provider,
        )
        workspace_id = getattr(preference, 'workspace_id', None)
        get_notification_cache_provider().invalidate_preference_cache(
            preference.user_id, workspace_id
        )

    def _notify_preference_change(self, preference):
        from components.notifications.application.providers.notification_factory_provider import (
            get_notification_factory_provider,
        )
        Notification = get_notifications_models_provider().Notification

        workspace = getattr(preference, "workspace", None)
        actor = getattr(self.request, "user", None)
        owner = getattr(workspace, "workspace_owner", None)
        if actor and owner and actor != owner:
            metadata = {
                "event": "notifications.preferences.workspace",
                "is_enabled": preference.is_enabled,
                "workspace": str(getattr(workspace, "id", "")),
            }
            notification_factory = get_notification_factory_provider()
            notification_factory.create_notification(
                recipient=owner,
                actor=actor,
                verb="updated notification preferences",
                notification_type=Notification.NotificationType.SYSTEM,
                workspace=workspace,
                metadata=metadata,
            )
            notification_factory.create_notification(
                recipient=actor,
                actor=owner,
                verb="updated your notification preferences",
                notification_type=Notification.NotificationType.SYSTEM,
                workspace=workspace,
                metadata=metadata,
            )


# ── AI Notification Preferences ──────────────────────────────────────────


class AINotificationPreferenceViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """AI notification preferences — pure CRUD."""

    serializer_class = AINotificationPreferenceSerializer
    permission_classes = (permissions.IsAuthenticated,)
    lookup_field = "workspace_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            AINotificationPreference = get_notifications_models_provider().AINotificationPreference
            return AINotificationPreference.objects.none()
        return _notifications_service.get_ai_preferences_queryset(self.request.user.id)

    def perform_create(self, serializer):
        pref = serializer.save(user=self.request.user)
        self._invalidate_pref_cache(pref)

    def perform_update(self, serializer):
        pref = serializer.save(user=self.request.user)
        self._invalidate_pref_cache(pref)

    @staticmethod
    def _invalidate_pref_cache(preference):
        from components.notifications.application.providers.notification_cache_provider import (
            get_notification_cache_provider,
        )
        workspace_id = getattr(preference, 'workspace_id', None)
        get_notification_cache_provider().invalidate_preference_cache(
            preference.user_id, workspace_id
        )


# ── User Notification Preferences ────────────────────────────────────────


class UserPreferenceView(APIView):
    """Create, read, update, and delete user notification preferences."""

    permission_classes = (IsUnauthenticatedOrAdminOrStaff,)
    serializer_class = UserPreferenceSerializer

    def post(self, request):
        serializer = UserPreferenceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        return Response({"status": "error", "data": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, uuid=None):
        if not uuid:
            return Response({"status": "error", "message": "User identifier required."}, status=status.HTTP_400_BAD_REQUEST)
        preference = _notifications_service.get_user_preference(uuid)
        serializer = UserPreferenceSerializer(preference, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "data": serializer.data})
        return Response({"status": "error", "data": serializer.errors})

    def get(self, request, uuid=None):
        if uuid:
            preference = _notifications_service.get_user_preference(uuid)
            serializer = UserPreferenceSerializer(preference)
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
        preferences = _notifications_service.list_user_preferences()
        serializer = UserPreferenceSerializer(preferences, many=True)
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request, uuid=None):
        _notifications_service.delete_user_preference(uuid)
        return Response({"status": "success", "data": "Item Deleted"})


@extend_schema_view(
    get=extend_schema(operation_id="userpreferences_detail_retrieve"),
    post=extend_schema(operation_id="userpreferences_detail_create"),
    patch=extend_schema(operation_id="userpreferences_detail_partial_update"),
    delete=extend_schema(operation_id="userpreferences_detail_destroy"),
)
class UserPreferenceDetailView(UserPreferenceView):
    """User preference detail view for unique schema operation IDs."""

    name = "userpreferences-detail"

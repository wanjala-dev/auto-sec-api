from __future__ import annotations

from rest_framework import serializers

from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.notifications.models import (
    AINotificationPreference,
    Notification,
    WorkspaceNotificationPreference,
)


class UserSummarySerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ('id', 'username', 'first_name', 'last_name', 'avatar')
        read_only_fields = fields

    def get_avatar(self, obj) -> str | None:  # pragma: no cover - simple accessor
        profile = getattr(obj, 'profile', None)
        return getattr(profile, 'photo_url', None)


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True)
    recipient = UserSummarySerializer(read_only=True)
    target = serializers.SerializerMethodField()
    workspace = serializers.SerializerMethodField()
    object_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        read_only_fields = (
            'id',
            'actor',
            'recipient',
            'verb',
            'notification_type',
            'metadata',
            'logo_url',
            'content_type',
            'object_id',
            'created_at',
            'updated_at',
            'read_at',
        )
        fields = read_only_fields + (
            'is_read',
            'target',
            'workspace',
        )

    def get_object_id(self, obj) -> int | str | None:
        return self._normalize_object_id(obj.object_id)

    def get_target(self, obj) -> dict[str, object] | None:
        if obj.content_type is None:
            return None
        return {
            'id': self._normalize_object_id(obj.object_id),
            'type': obj.content_type.model,
            'app_label': obj.content_type.app_label,
            'representation': str(obj.content_object) if obj.content_object else None,
        }

    def get_workspace(self, obj) -> dict[str, str] | None:
        workspace = getattr(obj, 'workspace', None)
        if not workspace:
            return None
        return {
            'id': str(workspace.id),
            'name': workspace.workspace_name,
        }

    @staticmethod
    def _normalize_object_id(value):
        if value is None:
            return None
        if isinstance(value, int):
            return value
        value_str = str(value)
        if value_str.isdigit():
            try:
                return int(value_str)
            except ValueError:
                pass
        return value_str


class WorkspaceNotificationPreferenceSerializer(serializers.ModelSerializer):
    workspace = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        pk_field=serializers.UUIDField(format='hex_verbose'),
    )

    class Meta:
        model = WorkspaceNotificationPreference
        fields = ('id', 'workspace', 'is_enabled')
        read_only_fields = ('id',)


class AINotificationPreferenceSerializer(serializers.ModelSerializer):
    workspace = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        pk_field=serializers.UUIDField(format='hex_verbose'),
    )

    class Meta:
        model = AINotificationPreference
        fields = ('id', 'workspace', 'channel', 'is_enabled')
        read_only_fields = ('id',)

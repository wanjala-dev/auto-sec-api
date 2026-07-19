from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from infrastructure.persistence.broadcast.models import Banner


class BannerSerializer(serializers.ModelSerializer):
    is_active_now = serializers.SerializerMethodField()
    scope_display = serializers.SerializerMethodField()
    severity_display = serializers.SerializerMethodField()
    workspace_name = serializers.CharField(source='workspace.workspace_name', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = Banner
        fields = [
            'id',
            'title',
            'message',
            'severity',
            'severity_display',
            'scope',
            'scope_display',
            'workspace',
            'workspace_name',
            'user',
            'user_email',
            'is_active',
            'dismissible',
            'priority',
            'starts_at',
            'ends_at',
            'created_at',
            'updated_at',
            'is_active_now',
        ]
        read_only_fields = ('created_at', 'updated_at')

    def get_is_active_now(self, obj) -> bool:
        return obj.is_active_now()

    def get_scope_display(self, obj) -> str:
        return obj.get_scope_display()

    def get_severity_display(self, obj) -> str:
        return obj.get_severity_display()

    def validate(self, attrs):
        scope = attrs.get('scope', getattr(self.instance, 'scope', Banner.Scope.SYSTEM))
        workspace = attrs.get('workspace', getattr(self.instance, 'workspace', None))
        user = attrs.get('user', getattr(self.instance, 'user', None))

        if scope == Banner.Scope.WORKSPACE and not workspace:
            raise serializers.ValidationError(_("A workspace must be provided when scope is 'workspace'."))
        if scope == Banner.Scope.USER and not user:
            raise serializers.ValidationError(_("A user must be provided when scope is 'user'."))

        if scope != Banner.Scope.WORKSPACE:
            attrs.setdefault('workspace', None)
        if scope != Banner.Scope.USER:
            attrs.setdefault('user', None)

        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(_("End time must be after the start time."))

        return attrs

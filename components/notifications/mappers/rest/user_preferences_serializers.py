from rest_framework import serializers

from infrastructure.persistence.notifications.userpreferences.models import UserPreference


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = [
            "id",
            "user",
            "darkmode",
            "language",
            "email_notifications",
            "push_notifications",
            "notifications_enabled",
            "ui_version",
            "recommendations_personalized",
        ]

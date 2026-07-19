"""DRF serializers for the membership bounded context.

Input serializers validate HTTP request bodies.
Output serializers render resource DTOs to JSON responses.

Invitation and member-related serializers extracted from
``components.team.mappers.rest.team_serializers``.
"""

from datetime import datetime

from rest_framework import serializers
from infrastructure.persistence.users.models import CustomUser


# ── Input serializers ────────────────────────────────────────────────


class InvitationRequestSerializer(serializers.Serializer):
    """Input schema for inviting members."""

    email = serializers.EmailField(required=False)
    emails = serializers.ListField(child=serializers.EmailField(), required=False)
    user_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    workspace = serializers.CharField()
    team = serializers.CharField(required=False)

    def validate(self, attrs):
        email = attrs.get("email")
        emails = attrs.get("emails") or []
        user_ids = attrs.get("user_ids") or []
        if not email and not emails and not user_ids:
            raise serializers.ValidationError("Provide email, emails, or user_ids.")
        return attrs


class InvitationAcceptSerializer(serializers.Serializer):
    """Input schema for accepting an invitation."""

    code = serializers.CharField()


# ── Output serializers ───────────────────────────────────────────────


class MembershipSummarySerializer(serializers.ModelSerializer):
    """Lightweight representation of a user plus the teams they belong to."""

    teams = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_active",
            "avatar_url",
            "teams",
        )

    def get_teams(self, obj):
        team_lookup = self.context.get("team_lookup", {})
        teams = team_lookup.get(obj.id, [])
        formatted = []
        for team in teams:
            joined_at = team.get("joined_at")
            if isinstance(joined_at, datetime):
                joined_value = joined_at.isoformat()
            else:
                joined_value = joined_at
            formatted.append(
                {
                    "id": team.get("id"),
                    "title": team.get("title"),
                    "joined_at": joined_value,
                }
            )
        return formatted

    def get_avatar_url(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "photo_url", "") if profile else ""


class PendingInvitationSerializer(serializers.Serializer):
    """Output schema for pending invitations."""

    email = serializers.EmailField()
    latest_sent = serializers.DateTimeField()
    teams = serializers.ListField(child=serializers.DictField(), allow_empty=True)

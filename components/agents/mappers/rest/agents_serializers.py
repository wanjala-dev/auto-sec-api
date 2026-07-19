from datetime import timedelta
import secrets
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from infrastructure.persistence.ai.agents.models import (
    Agent,
    AgentProfile,
    AgentFollow,
    AgentReaction,
    AgentRating,
    AgentComment,
    AgentShare,
)


class AgentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentProfile
        fields = [
            "display_name",
            "summary",
            "avatar_url",
            "tags",
            "visibility",
            "allow_followers",
            "allow_ratings",
            "allow_comments",
            "is_disabled",
        ]

    def validate_tags(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Tags must be a list of strings.")
        return [str(item) for item in value if item]


class AgentEngagementCountsSerializer(serializers.Serializer):
    likes = serializers.IntegerField()
    followers = serializers.IntegerField()
    rating_avg = serializers.FloatField()
    rating_count = serializers.IntegerField()
    comment_count = serializers.IntegerField()


class FollowSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentFollow
        fields = ["agent", "user", "created_at"]
        read_only_fields = ["created_at"]


class ReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentReaction
        fields = ["agent", "user", "reaction_type", "created_at"]
        read_only_fields = ["created_at"]


class RatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentRating
        fields = ["agent", "user", "score", "comment", "created_at"]
        read_only_fields = ["created_at"]


class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AgentComment
        fields = ["id", "agent", "user", "body", "parent", "created_at", "user_name"]
        read_only_fields = ["id", "created_at", "user_name"]

    def get_user_name(self, obj: AgentComment) -> str:
        if obj.user:
            return getattr(obj.user, "username", "") or getattr(obj.user, "email", "")
        return ""

    def validate_body(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Comment cannot be empty.")
        if len(value) > 2000:
            raise serializers.ValidationError("Comment is too long (max 2000 characters).")
        return value.strip()

    def validate_parent(self, value: AgentComment | None) -> AgentComment | None:
        if value and value.parent_id:
            if value.parent and value.parent.parent_id:
                raise serializers.ValidationError("Maximum comment depth exceeded.")
        return value


class ShareSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentShare
        fields = ["share_token", "scope", "expires_at", "created_at"]
        read_only_fields = ["share_token", "created_at"]

    def create(self, validated_data: dict[str, Any]) -> AgentShare:
        expires_at = validated_data.get("expires_at")
        if expires_at is None:
            validated_data["expires_at"] = timezone.now() + timedelta(days=14)
        return super().create(validated_data)

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)

"""REST serializers for the messaging bounded context.

These serializers map between HTTP request/response bodies and the
domain entities.  They do NOT import ORM models — they serialize
domain entity dataclasses that the use cases return.
"""

from __future__ import annotations

from rest_framework import serializers


# ── Input serializers ───────────────────────────────────────────────


class StartConversationSerializer(serializers.Serializer):
    recipient_id = serializers.UUIDField()
    workspace_id = serializers.UUIDField(required=False, allow_null=True)


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField(
        max_length=10000, required=False, allow_blank=True, default=""
    )
    message_type = serializers.ChoiceField(
        choices=["text", "image", "system"],
        default="text",
    )
    image = serializers.ImageField(required=False, allow_null=True)
    # Structured card payload (Share in chat). Size-capped so a client
    # can't stuff arbitrary blobs into chat rows.
    metadata = serializers.JSONField(required=False)

    MAX_METADATA_BYTES = 4 * 1024

    def validate_metadata(self, value):
        import json

        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be an object.")
        if len(json.dumps(value)) > self.MAX_METADATA_BYTES:
            raise serializers.ValidationError("metadata too large.")
        return value

    MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

    def validate_image(self, image):
        if image is None:
            return image
        if image.size > self.MAX_IMAGE_BYTES:
            raise serializers.ValidationError("Image must be 5 MB or smaller.")
        content_type = getattr(image, "content_type", None)
        if content_type and content_type not in self.ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError(
                "Unsupported image type. Use JPEG, PNG, WebP, or GIF."
            )
        return image

    def validate(self, attrs):
        body = (attrs.get("body") or "").strip()
        if not body and not attrs.get("image"):
            raise serializers.ValidationError(
                "A message must have text or an image."
            )
        return attrs


# ── Output serializers ──────────────────────────────────────────────


class ParticipantSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.CharField()
    is_archived = serializers.BooleanField()
    is_starred = serializers.BooleanField()
    is_muted = serializers.BooleanField()
    last_read_at = serializers.DateTimeField(allow_null=True)
    joined_at = serializers.DateTimeField(allow_null=True)


class ParticipantSummarySerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField(allow_blank=True)
    avatar_url = serializers.CharField(allow_blank=True)
    initials = serializers.CharField(allow_blank=True)


class LastMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sender_id = serializers.UUIDField()
    body = serializers.CharField(allow_blank=True)
    message_type = serializers.CharField()
    created_at = serializers.DateTimeField(allow_null=True)


class ConversationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    conversation_type = serializers.CharField()
    workspace_id = serializers.UUIDField(allow_null=True)
    participants = ParticipantSerializer(many=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    other_participant = ParticipantSummarySerializer(allow_null=True, required=False)
    last_message = LastMessageSerializer(allow_null=True, required=False)
    unread_count = serializers.IntegerField(default=0)


class MessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    conversation_id = serializers.UUIDField()
    sender_id = serializers.UUIDField()
    body = serializers.CharField()
    message_type = serializers.CharField()
    image = serializers.CharField(allow_null=True)
    metadata = serializers.JSONField(required=False, default=dict)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    is_deleted = serializers.BooleanField()


class UnreadCountSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField()
    count = serializers.IntegerField()

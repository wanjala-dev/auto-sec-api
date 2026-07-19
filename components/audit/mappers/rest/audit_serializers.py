"""REST serializers for audit log entries."""

from rest_framework import serializers

from infrastructure.persistence.audit.models import EntityAuditLog


class EntityAuditLogSerializer(serializers.ModelSerializer):
    entity_type = serializers.SerializerMethodField()
    actor_display = serializers.SerializerMethodField()

    class Meta:
        model = EntityAuditLog
        fields = [
            "id",
            "entity_type",
            "object_id",
            "field_name",
            "previous_value",
            "new_value",
            "actor",
            "actor_display",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_entity_type(self, obj):
        ct = obj.content_type
        return f"{ct.app_label}.{ct.model}" if ct else ""

    def get_actor_display(self, obj):
        actor = obj.actor
        if actor is None:
            return "System"
        full = " ".join(
            part
            for part in (
                getattr(actor, "first_name", "") or "",
                getattr(actor, "last_name", "") or "",
            )
            if part
        )
        return (
            full
            or getattr(actor, "email", "")
            or getattr(actor, "username", "")
            or "Unknown"
        )

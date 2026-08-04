"""REST serializers for audit log entries.

Serializes the framework-free ``AuditEntry`` domain entity returned by
the audit use cases — the controller never touches ORM rows. The JSON
contract is unchanged from the previous ModelSerializer:
``id, entity_type, object_id, field_name, previous_value, new_value,
actor, actor_display, reason, created_at``.
"""

from rest_framework import serializers


class AuditEntrySerializer(serializers.Serializer):
    """Read-only projection of ``AuditEntry`` for the REST adapter."""

    id = serializers.CharField(read_only=True)
    entity_type = serializers.CharField(read_only=True)
    object_id = serializers.CharField(source="entity_id", read_only=True)
    field_name = serializers.CharField(read_only=True)
    previous_value = serializers.JSONField(read_only=True, allow_null=True)
    new_value = serializers.JSONField(read_only=True, allow_null=True)
    actor = serializers.CharField(source="actor_id", read_only=True, allow_null=True)
    actor_display = serializers.SerializerMethodField()
    reason = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)

    def get_actor_display(self, entry) -> str:
        # Contract parity with the previous ModelSerializer: system
        # writes render as "System", actors with no resolvable name as
        # "Unknown".
        if entry.actor_display:
            return entry.actor_display
        return "System" if entry.actor_id is None else "Unknown"

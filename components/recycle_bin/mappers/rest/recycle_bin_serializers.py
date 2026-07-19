from rest_framework import serializers


class RecycleBinEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    entity_type = serializers.CharField()
    # CharField (not UUIDField) so the API can return entity_ids for
    # entities with integer PKs as well as UUIDs.
    entity_id = serializers.CharField()
    entity_name = serializers.CharField()
    stage = serializers.CharField()
    deleted_by = serializers.UUIDField(allow_null=True)
    deleted_at = serializers.DateTimeField()
    trashed_until = serializers.DateTimeField()
    tombstoned_at = serializers.DateTimeField(allow_null=True)
    snapshot = serializers.DictField(default=dict)

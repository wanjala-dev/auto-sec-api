"""Serializers for the shared DocumentImport pipeline."""
from __future__ import annotations

from rest_framework import serializers

from infrastructure.persistence.imports.models import (
    DocumentImport,
    DocumentImportRow,
)


class DocumentImportRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentImportRow
        fields = [
            "id",
            "document_import",
            "row_index",
            "label",
            "amount",
            "date",
            "category_name",
            "row_type",
            "notes",
            "parsed_data",
            "is_valid",
            "validation_errors",
            "user_modified",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "document_import",
            "created_at",
            "updated_at",
        ]


class DocumentImportSerializer(serializers.ModelSerializer):
    source_file_url = serializers.SerializerMethodField()
    is_retryable = serializers.SerializerMethodField()

    class Meta:
        model = DocumentImport
        fields = [
            "id",
            "workspace",
            "uploaded_by",
            "source_file",
            "source_file_url",
            "original_filename",
            "import_type",
            "source_format",
            "status",
            "row_count",
            "valid_row_count",
            "applied_row_count",
            "summary",
            "config",
            "use_ai",
            "error_message",
            "queued_at",
            "processed_at",
            "applied_at",
            "created_at",
            "updated_at",
            "last_heartbeat_at",
            "retry_count",
            "is_retryable",
        ]
        read_only_fields = [
            "id",
            "uploaded_by",
            "source_format",
            "status",
            "row_count",
            "valid_row_count",
            "applied_row_count",
            "summary",
            "error_message",
            "queued_at",
            "processed_at",
            "applied_at",
            "created_at",
            "updated_at",
            "last_heartbeat_at",
            "retry_count",
            "is_retryable",
        ]

    def get_is_retryable(self, obj) -> bool:
        # Any import with a source file that's either failed or still
        # sitting in an active state can be retried — the latter covers
        # the "been hung for 20 min and I'm impatient" case.
        if not obj.source_file_id:
            return False
        return obj.status in (
            DocumentImport.STATUS_FAILED,
            DocumentImport.STATUS_PARSING,
            DocumentImport.STATUS_PENDING,
            DocumentImport.STATUS_QUEUED,
        )

    def get_source_file_url(self, obj):
        if not obj.source_file:
            return None
        request = self.context.get("request")
        return obj.source_file.get_absolute_file_url(request=request)


class DocumentImportCreateSerializer(serializers.Serializer):
    """Used for the create endpoint — accepts workspace + file + type."""

    workspace = serializers.CharField()
    source_file = serializers.IntegerField(
        help_text="ID of the uploaded File record."
    )
    import_type = serializers.ChoiceField(
        choices=DocumentImport.TYPE_CHOICES,
        default="expense",
    )
    use_ai = serializers.BooleanField(default=True)
    config = serializers.JSONField(required=False, default=dict)

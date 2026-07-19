from rest_framework import serializers

from infrastructure.persistence.uploads.models import File


class FileSerializer(serializers.ModelSerializer):
    owner = serializers.SlugRelatedField(read_only=True, slug_field='id')
    file = serializers.FileField(required=False)
    file_path = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = [
            'pk', 'url', 'created', 'file', 'file_path', 'owner',
            'file_type', 'processing_status', 'processing_error',
            'processed_at', 'pdf_text', 'pdf_page_count'
        ]
        read_only_fields = (
            'created', 'file', 'file_path', 'owner', 'processing_status',
            'processing_error', 'processed_at', 'pdf_text', 'pdf_page_count'
        )

    def get_file_path(self, obj):
        return obj.file.name if obj.file else ""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        data['file'] = instance.get_absolute_file_url(request)
        return data

"""
Conversations Serializers
"""
from rest_framework import serializers
from infrastructure.persistence.ai.conversations.models import Conversation, ConversationMessage


class ConversationMessageSerializer(serializers.ModelSerializer):
    """Serializer for ConversationMessage model"""

    feedback_counts = serializers.SerializerMethodField()
    my_feedback = serializers.SerializerMethodField()

    class Meta:
        model = ConversationMessage
        fields = [
            'id', 'role', 'content', 'created_at', 'metadata',
            'feedback_counts', 'my_feedback',
        ]
        read_only_fields = ['id', 'created_at']

    def _feedback_queryset(self, obj):
        """Return the related feedback queryset (prefetched in practice)."""
        return obj.feedback.all()

    def get_feedback_counts(self, obj):
        """Return aggregate thumbs-up / thumbs-down counts across all users."""
        counts = {'up': 0, 'down': 0}
        for fb in self._feedback_queryset(obj):
            if fb.rating in counts:
                counts[fb.rating] += 1
        return counts

    def get_my_feedback(self, obj):
        """Return the requesting user's rating on this message, if any."""
        request = self.context.get('request')
        if not request or not getattr(request, 'user', None) or not request.user.is_authenticated:
            return None
        user_id = request.user.id
        for fb in self._feedback_queryset(obj):
            if fb.user_id == user_id:
                return fb.rating
        return None


class ConversationSerializer(serializers.ModelSerializer):
    """Serializer for Conversation model"""

    messages = ConversationMessageSerializer(many=True, read_only=True)
    message_count = serializers.SerializerMethodField()
    pdf_id = serializers.SerializerMethodField()
    workspace_id = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'title', 'user', 'created_at', 'updated_at',
            'is_active', 'metadata', 'messages', 'message_count', 'pdf_id', 'workspace_id'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'user']

    def get_message_count(self, obj):
        """Get the number of messages in the conversation"""
        return obj.messages.count()

    def get_pdf_id(self, obj):
        """Get PDF ID from metadata"""
        return obj.metadata.get('pdf_id')

    def get_workspace_id(self, obj):
        """Get workspace ID from metadata"""
        return obj.metadata.get('workspace_id')

    def create(self, validated_data):
        """Create conversation with user from request context"""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['user'] = request.user
        return super().create(validated_data)


class ConversationListSerializer(serializers.ModelSerializer):
    """Simplified serializer for conversation lists"""

    # Annotated by ``OrmConversationRepository.list_for_user`` (Count over the
    # messages reverse FK). A per-row ``obj.messages.count()`` here was an N+1
    # on an UNPAGINATED list — it scaled with the user's whole chat history.
    message_count = serializers.IntegerField(read_only=True)
    pdf_id = serializers.SerializerMethodField()
    workspace_id = serializers.SerializerMethodField()
    agent_type = serializers.SerializerMethodField()
    agent_id = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'title', 'created_at', 'updated_at',
            'is_active', 'message_count', 'pdf_id', 'workspace_id',
            'agent_type', 'agent_id', 'metadata',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_pdf_id(self, obj):
        """Get PDF ID from metadata"""
        return obj.metadata.get('pdf_id')

    def get_workspace_id(self, obj):
        """Get workspace ID from metadata"""
        return obj.metadata.get('workspace_id')

    def get_agent_type(self, obj):
        """Get agent type from metadata (e.g. 'workspace_agent')."""
        return obj.metadata.get('agent_type')

    def get_agent_id(self, obj):
        """Get owning agent id from metadata."""
        return obj.metadata.get('agent_id')


class CreateConversationSerializer(serializers.Serializer):
    """Serializer for creating conversations"""

    pdf_id = serializers.CharField(required=True)
    workspace_id = serializers.CharField(required=True)
    title = serializers.CharField(required=False, allow_blank=True)

    def validate_pdf_id(self, value):
        """Validate that the document file exists and is supported"""
        from infrastructure.persistence.uploads.models import File
        try:
            file_obj = File.objects.get(id=value)
            if file_obj.file_type not in ('pdf', 'document'):
                raise serializers.ValidationError("File is not a supported document")
        except File.DoesNotExist:
            raise serializers.ValidationError("Document with this ID does not exist")
        return value

    def validate_workspace_id(self, value):
        """Validate that the workspace exists"""
        from infrastructure.persistence.workspaces.models import Workspace
        try:
            Workspace.objects.get(id=value)
        except Workspace.DoesNotExist:
            raise serializers.ValidationError("Workspace with this ID does not exist")
        return value


class CreateMessageSerializer(serializers.Serializer):
    """Serializer for creating messages"""

    input = serializers.CharField(required=True, max_length=10000)
    streaming = serializers.BooleanField(required=False, default=False)

    def validate_input(self, value):
        """Validate input message"""
        if not value.strip():
            raise serializers.ValidationError("Input cannot be empty")
        return value.strip()

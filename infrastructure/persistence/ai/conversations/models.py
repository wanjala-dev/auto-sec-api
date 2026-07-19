"""
Conversations Models
"""
from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


class Conversation(models.Model):
    """Model for storing conversation sessions"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_conversations', null=True, blank=True, default=None)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-updated_at']
        db_table = 'ai_conversations'
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'
        indexes = [
            models.Index(fields=['-updated_at'], name='ai_conv_updated_idx'),
            models.Index(fields=['user', '-updated_at'], name='ai_conv_user_updated_idx'),
        ]
    
    def __str__(self):
        return f"Conversation {self.id} - {self.title or 'Untitled'}"
    
    @property
    def pdf_id(self):
        """Get PDF ID from metadata"""
        return self.metadata.get('pdf_id')
    
    @pdf_id.setter
    def pdf_id(self, value):
        """Set PDF ID in metadata"""
        if not self.metadata:
            self.metadata = {}
        self.metadata['pdf_id'] = value


class ConversationMessage(models.Model):
    """Model for storing individual messages in conversations"""
    
    ROLE_CHOICES = [
        ('human', 'Human'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, 
        on_delete=models.CASCADE, 
        related_name='messages'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['created_at']
        db_table = 'ai_conversation_messages'
        verbose_name = 'Conversation Message'
        verbose_name_plural = 'Conversation Messages'
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='ai_msg_conv_created_idx'),
            models.Index(fields=['-created_at'], name='ai_msg_created_idx'),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


class AgentResponseFeedback(models.Model):
    """User feedback (thumbs up / thumbs down) on an assistant message."""

    RATING_UP = 'up'
    RATING_DOWN = 'down'
    RATING_CHOICES = [
        (RATING_UP, 'Thumbs up'),
        (RATING_DOWN, 'Thumbs down'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        ConversationMessage,
        on_delete=models.CASCADE,
        related_name='feedback',
    )
    user = models.ForeignKey(
        'users.CustomUser',
        on_delete=models.CASCADE,
        related_name='agent_response_feedback',
    )
    rating = models.CharField(max_length=4, choices=RATING_CHOICES)
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_agent_response_feedback'
        verbose_name = 'Agent response feedback'
        verbose_name_plural = 'Agent response feedback'
        constraints = [
            models.UniqueConstraint(
                fields=['message', 'user'],
                name='uniq_message_user_feedback',
            ),
        ]
        indexes = [
            models.Index(fields=['message', 'rating'], name='ai_fb_msg_rating_idx'),
            models.Index(fields=['-created_at'], name='ai_fb_created_idx'),
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.message_id}: {self.rating}"

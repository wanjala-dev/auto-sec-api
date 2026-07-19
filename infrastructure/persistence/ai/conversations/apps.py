from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    """Conversations app configuration"""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'infrastructure.persistence.ai.conversations'
    verbose_name = 'AI Conversations'

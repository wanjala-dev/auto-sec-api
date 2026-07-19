from django.apps import AppConfig


class KnowledgeCLIConfig(AppConfig):
    name = 'components.knowledge.cli'
    label = 'knowledge_cli'
    verbose_name = 'Knowledge CLI'
    default_auto_field = 'django.db.models.BigAutoField'

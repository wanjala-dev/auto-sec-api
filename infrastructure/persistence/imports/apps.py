from django.apps import AppConfig


class ImportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.imports"
    verbose_name = "Document Imports"

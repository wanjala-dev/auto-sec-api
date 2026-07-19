from django.apps import AppConfig


class SecurityTemplatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.security_templates"
    label = "security_templates"
    verbose_name = "Security Report Templates"

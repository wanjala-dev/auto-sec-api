from django.apps import AppConfig


class CodeSecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.code_security"
    label = "code_security"

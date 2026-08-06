from django.apps import AppConfig


class ContainerSecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.container_security"
    label = "container_security"

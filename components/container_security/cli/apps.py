from django.apps import AppConfig


class ContainerSecurityCLIConfig(AppConfig):
    name = "components.container_security.cli"
    label = "container_security_cli"
    verbose_name = "Container Security CLI"
    default_auto_field = "django.db.models.BigAutoField"

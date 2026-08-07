from django.apps import AppConfig


class CodeSecurityCLIConfig(AppConfig):
    name = "components.code_security.cli"
    label = "code_security_cli"
    verbose_name = "Code Security CLI"
    default_auto_field = "django.db.models.BigAutoField"

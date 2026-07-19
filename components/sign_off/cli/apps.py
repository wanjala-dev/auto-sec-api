from django.apps import AppConfig


class SignOffCLIConfig(AppConfig):
    name = "components.sign_off.cli"
    label = "sign_off_cli"
    verbose_name = "Sign-Off CLI"
    default_auto_field = "django.db.models.BigAutoField"

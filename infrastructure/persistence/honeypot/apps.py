from django.apps import AppConfig


class HoneypotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.honeypot"
    verbose_name = "Admin Honeypot"

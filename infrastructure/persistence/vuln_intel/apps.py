from django.apps import AppConfig


class VulnIntelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.vuln_intel"
    label = "vuln_intel"

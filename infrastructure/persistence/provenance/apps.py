from django.apps import AppConfig


class ProvenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.provenance"
    label = "provenance"

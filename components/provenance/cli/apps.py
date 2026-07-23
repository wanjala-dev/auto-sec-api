from django.apps import AppConfig


class ProvenanceCLIConfig(AppConfig):
    name = "components.provenance.cli"
    label = "provenance_cli"
    verbose_name = "Provenance CLI"
    default_auto_field = "django.db.models.BigAutoField"

from django.apps import AppConfig


class ProvenanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.provenance"
    label = "provenance"

    def ready(self):
        # Stamp the canonical asset_urn on every ProvenanceResource write (ADR 0004 D2).
        from components.provenance.infrastructure.adapters.django_asset_urn_signal_bridge import (
            DjangoProvenanceAssetUrnBridge,
        )

        DjangoProvenanceAssetUrnBridge.register()

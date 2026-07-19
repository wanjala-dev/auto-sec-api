from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "infrastructure.persistence.core"
    verbose_name = "Core utilities"

    def ready(self):
        from components.shared_platform.infrastructure.adapters.django_feature_flag_signal_bridge import (
            DjangoFeatureFlagSignalBridge,
        )

        DjangoFeatureFlagSignalBridge.register()

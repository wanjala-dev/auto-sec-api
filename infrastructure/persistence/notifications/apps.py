from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'infrastructure.persistence.notifications'
    label = 'core_notifications'
    verbose_name = 'Notifications'

    def ready(self):
        from components.shared_kernel.application.providers.default_notification_catalog_provider import (
            DefaultNotificationCatalogProvider,
        )

        DefaultNotificationCatalogProvider().register_defaults()

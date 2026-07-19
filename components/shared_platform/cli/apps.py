from django.apps import AppConfig


class SharedPlatformCLIConfig(AppConfig):
    name = 'components.shared_platform.cli'
    label = 'shared_platform_cli'
    verbose_name = 'Shared Platform CLI'
    default_auto_field = 'django.db.models.BigAutoField'

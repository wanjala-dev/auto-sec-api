from django.apps import AppConfig


class IdentityCLIConfig(AppConfig):
    name = 'components.identity.cli'
    label = 'identity_cli'
    verbose_name = 'Identity CLI'
    default_auto_field = 'django.db.models.BigAutoField'

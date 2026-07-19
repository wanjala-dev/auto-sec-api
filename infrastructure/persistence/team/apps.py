from django.apps import AppConfig


class TeamConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'infrastructure.persistence.team'

    def ready(self):
        from components.team.infrastructure.adapters import checks  # noqa: F401

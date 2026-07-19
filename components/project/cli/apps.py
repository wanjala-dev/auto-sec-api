from django.apps import AppConfig


class ProjectCLIConfig(AppConfig):
    name = 'components.project.cli'
    label = 'project_cli'
    verbose_name = 'Project CLI'
    default_auto_field = 'django.db.models.BigAutoField'

from django.apps import AppConfig


class WorkspaceCLIConfig(AppConfig):
    name = 'components.workspace.cli'
    label = 'workspace_cli'
    verbose_name = 'Workspace CLI'
    default_auto_field = 'django.db.models.BigAutoField'

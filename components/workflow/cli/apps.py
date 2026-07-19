from django.apps import AppConfig


class WorkflowCLIConfig(AppConfig):
    name = 'components.workflow.cli'
    label = 'workflow_cli'
    verbose_name = 'Workflow CLI'
    default_auto_field = 'django.db.models.BigAutoField'

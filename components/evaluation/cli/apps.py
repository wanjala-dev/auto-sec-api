from django.apps import AppConfig


class EvaluationCLIConfig(AppConfig):
    name = "components.evaluation.cli"
    label = "evaluation_cli"
    verbose_name = "Evaluation CLI"
    default_auto_field = "django.db.models.BigAutoField"

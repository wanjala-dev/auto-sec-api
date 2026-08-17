from django.apps import AppConfig


class ProjectCLIConfig(AppConfig):
    name = "components.project.cli"
    label = "project_cli"
    verbose_name = "Project CLI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # ADR 0030 P1 dual-write: every Column/Task save mirrors the column's
        # workflow status. Explicit bridge registration (repo convention —
        # signal bridges from ready(), never @receiver).
        from components.project.infrastructure.adapters.django_workflow_status_sync_bridge import (
            DjangoWorkflowStatusSyncBridge,
        )

        DjangoWorkflowStatusSyncBridge.register()

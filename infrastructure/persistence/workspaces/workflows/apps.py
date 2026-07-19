from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = "infrastructure.persistence.workspaces.workflows"
    label = 'workflows'

    def ready(self) -> None:
        # Phase 3 sign-off: register the workflow-email adapter with the kernel
        # so ``require_approved("workflow_email", id)`` and the (Phase 6) review
        # queue resolve against the parked WorkflowStepState row. An AI-derived
        # workflow email can never auto-send unreviewed.
        from components.workflow.infrastructure.adapters.workflow_email_sign_off_adapter import (
            WorkflowEmailSignOffAdapter,
        )
        from components.sign_off.application.providers.sign_off_registry_provider import (
            get_sign_off_registry,
        )

        get_sign_off_registry().register(WorkflowEmailSignOffAdapter())

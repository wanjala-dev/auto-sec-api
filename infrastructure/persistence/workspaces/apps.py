from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    name = "infrastructure.persistence.workspaces"

    def ready(self):
        from components.workspace.application.providers.workspace_signal_provider import (
            WorkspaceSignalProvider,
        )

        WorkspaceSignalProvider().register_signal_handlers()

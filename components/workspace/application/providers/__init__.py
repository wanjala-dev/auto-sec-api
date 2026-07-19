"""Providers for workspace application composition."""

from components.workspace.application.providers.workspace_setup_query_provider import (
    WorkspaceSetupQueryProvider,
)
from components.workspace.application.providers.workspace_bootstrap_provider import (
    WorkspaceBootstrapProvider,
)

__all__ = ["WorkspaceBootstrapProvider", "WorkspaceSetupQueryProvider"]

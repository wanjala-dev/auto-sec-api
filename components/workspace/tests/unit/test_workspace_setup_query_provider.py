from __future__ import annotations

from components.workspace.application.providers.workspace_setup_query_provider import (
    WorkspaceSetupQueryProvider,
)
from components.workspace.application.queries.workspace_setup_query import (
    WorkspaceSetupQueryService,
)


def test_workspace_setup_query_provider_builds_service():
    service = WorkspaceSetupQueryProvider().build_service()

    assert isinstance(service, WorkspaceSetupQueryService)

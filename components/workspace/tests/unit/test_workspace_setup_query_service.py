from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.application.queries.workspace_setup_query import (
    WorkspaceSetupQueryService,
)
from components.workspace.domain.policies.workspace_setup_policy_service import (
    WorkspaceSetupPolicyService,
    WorkspaceSetupSnapshot,
)


def test_workspace_setup_query_service_delegates_annotation():
    queries = SimpleNamespace(annotate_setup_state=Mock(return_value="annotated"))
    service = WorkspaceSetupQueryService(
        workspace_setup_queries=queries,
        workspace_setup_policy=WorkspaceSetupPolicyService(),
    )

    annotated = service.annotate_setup_state("queryset")

    assert annotated == "annotated"
    queries.annotate_setup_state.assert_called_once_with("queryset")


def test_workspace_setup_query_service_builds_status_from_snapshot():
    snapshot = WorkspaceSetupSnapshot(
        workspace_id="workspace-1",
        workspace_name="Alpha",
        has_contribution_means=True,
        has_story=True,
        has_cover_photo=False,
        has_budget=True,
        has_active_team=True,
    )
    queries = SimpleNamespace(build_setup_snapshot=Mock(return_value=snapshot))
    service = WorkspaceSetupQueryService(
        workspace_setup_queries=queries,
        workspace_setup_policy=WorkspaceSetupPolicyService(),
    )

    status = service.build_status("workspace-object")

    assert status["pending"] == ["has_cover_photo"]
    queries.build_setup_snapshot.assert_called_once_with("workspace-object")

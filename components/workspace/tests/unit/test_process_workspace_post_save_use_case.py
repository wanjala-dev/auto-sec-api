from __future__ import annotations

from types import SimpleNamespace

from components.workspace.application.use_cases.process_workspace_post_save_use_case import (
    ProcessWorkspacePostSaveUseCase,
)


class _WorkspacePostSavePort:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_embeddings(self, *, workspace) -> None:
        self.calls.append(("enqueue_embeddings", workspace))

    def bootstrap_defaults(self, *, workspace) -> None:
        self.calls.append(("bootstrap_defaults", workspace))


class _AiTeammateUseCase:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, *, workspace) -> None:
        self.calls.append(workspace)


def test_process_workspace_post_save_use_case_bootstraps_on_create():
    workspace = SimpleNamespace(id="workspace-1")
    port = _WorkspacePostSavePort()
    ai_use_case = _AiTeammateUseCase()
    use_case = ProcessWorkspacePostSaveUseCase(
        workspace_post_save_port=port,
        ai_teammate_use_case=ai_use_case,
    )

    use_case.execute(workspace=workspace, created=True)

    assert port.calls == [
        ("enqueue_embeddings", workspace),
        ("bootstrap_defaults", workspace),
    ]
    assert ai_use_case.calls == [workspace]


def test_process_workspace_post_save_use_case_skips_bootstrap_on_update():
    workspace = SimpleNamespace(id="workspace-1")
    port = _WorkspacePostSavePort()
    ai_use_case = _AiTeammateUseCase()
    use_case = ProcessWorkspacePostSaveUseCase(
        workspace_post_save_port=port,
        ai_teammate_use_case=ai_use_case,
    )

    use_case.execute(workspace=workspace, created=False)

    assert port.calls == [("enqueue_embeddings", workspace)]
    assert ai_use_case.calls == [workspace]

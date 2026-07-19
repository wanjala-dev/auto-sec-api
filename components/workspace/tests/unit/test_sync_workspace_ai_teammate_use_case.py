from components.team.application.use_cases.sync_workspace_ai_teammate_use_case import (
    SyncWorkspaceAiTeammateUseCase,
)


class _FakeWorkspaceAiTeammateSyncPort:
    def __init__(self) -> None:
        self.calls = []

    def sync(self, *, workspace) -> None:
        self.calls.append(workspace)


def test_sync_workspace_ai_teammate_use_case_delegates_to_port():
    port = _FakeWorkspaceAiTeammateSyncPort()
    use_case = SyncWorkspaceAiTeammateUseCase(
        workspace_ai_teammate_sync_port=port,
    )
    workspace = object()

    use_case.execute(workspace=workspace)

    assert port.calls == [workspace]

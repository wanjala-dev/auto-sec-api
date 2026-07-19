from components.workspace.application.use_cases.process_workspace_post_save_use_case import (
    ProcessWorkspacePostSaveUseCase,
)
from components.team.application.use_cases.sync_workspace_ai_teammate_use_case import (
    SyncWorkspaceAiTeammateUseCase,
)
from components.workspace.application.providers.workspace_signal_provider import (
    WorkspaceSignalProvider,
)
from components.workspace.infrastructure.adapters.django_workspace_signal_bridge import (
    DjangoWorkspaceSignalBridge,
)
from components.workspace.infrastructure.adapters.workspace_post_save_adapter import (
    WorkspacePostSaveAdapter,
)
from components.team.infrastructure.adapters.workspace_ai_teammate_sync_adapter import (
    WorkspaceAiTeammateSyncAdapter,
)


def test_workspace_signal_provider_builds_post_save_use_case():
    provider = WorkspaceSignalProvider()

    use_case = provider.build_post_save_use_case()

    assert isinstance(use_case, ProcessWorkspacePostSaveUseCase)
    assert isinstance(use_case.workspace_post_save_port, WorkspacePostSaveAdapter)
    assert isinstance(use_case.ai_teammate_use_case, SyncWorkspaceAiTeammateUseCase)


def test_workspace_signal_provider_registers_signal_handlers(monkeypatch):
    provider = WorkspaceSignalProvider()
    captured = {}

    class _Bridge:
        def register(self, *, handler) -> None:
            captured["handler"] = handler

    monkeypatch.setattr(
        "components.workspace.application.providers.workspace_signal_provider.DjangoWorkspaceSignalBridge",
        lambda: _Bridge(),
    )

    provider.register_signal_handlers()

    assert isinstance(captured["handler"], ProcessWorkspacePostSaveUseCase)


def test_workspace_signal_provider_builds_ai_teammate_sync_use_case():
    provider = WorkspaceSignalProvider()

    use_case = provider.build_sync_ai_teammate_use_case()

    assert isinstance(use_case, SyncWorkspaceAiTeammateUseCase)
    assert isinstance(
        use_case.workspace_ai_teammate_sync_port,
        WorkspaceAiTeammateSyncAdapter,
    )

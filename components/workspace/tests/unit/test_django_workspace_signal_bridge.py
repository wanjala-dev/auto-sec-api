from __future__ import annotations

from types import SimpleNamespace

from components.workspace.infrastructure.adapters.django_workspace_signal_bridge import (
    DjangoWorkspaceSignalBridge,
)


def test_django_workspace_signal_bridge_routes_signal_to_handler():
    bridge = DjangoWorkspaceSignalBridge()
    recorded = {}

    class _Handler:
        def execute(self, *, workspace, created):
            recorded["workspace"] = workspace
            recorded["created"] = created

    workspace = SimpleNamespace(id="workspace-1")
    receiver = bridge._build_receiver(handler=_Handler())

    receiver(sender=object(), instance=workspace, created=True)

    assert recorded == {"workspace": workspace, "created": True}


def test_django_workspace_signal_bridge_swallows_handler_errors():
    bridge = DjangoWorkspaceSignalBridge()

    class _Handler:
        def execute(self, *, workspace, created):
            raise RuntimeError("boom")

    receiver = bridge._build_receiver(handler=_Handler())

    receiver(sender=object(), instance=object(), created=False)

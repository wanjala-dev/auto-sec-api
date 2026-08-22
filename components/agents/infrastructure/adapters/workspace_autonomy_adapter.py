"""Adapter: read a workspace's autonomy mode via the ``workspace`` context.

Implements :class:`WorkspaceAutonomyPort` by delegating to ``workspace``'s
application surface (``GetWorkspaceAutonomyModeUseCase`` via
``WorkspaceAutonomyProvider``) — a permitted cross-context call into another
context's application layer, never its infrastructure/persistence. The same
shape as ``WorkspaceAiToggleAdapter`` beside it.

Nothing is caught here. A failed read must reach the gate so it can hold writes
rather than silently continuing under a guessed policy — see the port docstring.
"""

from __future__ import annotations

from components.agents.application.ports.workspace_autonomy_port import WorkspaceAutonomyPort


class WorkspaceAutonomyAdapter(WorkspaceAutonomyPort):
    def get_mode(self, *, workspace_id: str) -> str | None:
        from components.workspace.application.providers.workspace_autonomy_provider import (
            WorkspaceAutonomyProvider,
        )

        use_case = WorkspaceAutonomyProvider.build_get_workspace_autonomy_mode_use_case()
        return use_case.execute(workspace_id=str(workspace_id))

"""Adapter: flip a workspace's AI-teammate flag via the ``workspace`` context.

Implements :class:`WorkspaceAiTogglePort` by delegating to ``workspace``'s
application surface (``SetWorkspaceAiEnabledUseCase`` via
``WorkspaceAiToggleProvider``) — a permitted cross-context call into another
context's application layer, never its infrastructure/persistence (the same
shape as integrations' ``ProjectFindingPrRecorder`` delegating to ``project``).
``Workspace.ai_teammate_enabled`` is the workspace context's data, so the
workspace context owns the write; agents only asks for it and never imports a
workspace model.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.workspace_ai_toggle_port import (
    WorkspaceAiToggleOutcome,
    WorkspaceAiTogglePort,
)


class WorkspaceAiToggleAdapter(WorkspaceAiTogglePort):
    def set_ai_enabled(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        actor: Any,
        reason: str,
    ) -> WorkspaceAiToggleOutcome:
        from components.workspace.application.providers.workspace_ai_toggle_provider import (
            WorkspaceAiToggleProvider,
        )

        use_case = WorkspaceAiToggleProvider.build_set_workspace_ai_enabled_use_case()
        result = use_case.execute(
            workspace_id=str(workspace_id),
            enabled=bool(enabled),
            actor=actor,
            reason=reason,
        )
        return WorkspaceAiToggleOutcome(previous=result.previous, changed=result.changed)

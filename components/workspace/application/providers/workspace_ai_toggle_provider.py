"""Composition root for the workspace AI-teammate toggle use case.

Wires the ORM-backed :class:`WorkspaceAiToggleRepository` to the
:class:`SetWorkspaceAiEnabledUseCase` (architecture-manifesto Rule 9 — providers
own the port→adapter wiring). The agents context reaches this write through its
own port + adapter, which call ``build_set_workspace_ai_enabled_use_case``.
"""

from __future__ import annotations

from components.workspace.application.use_cases.set_workspace_ai_enabled_use_case import (
    SetWorkspaceAiEnabledUseCase,
)


class WorkspaceAiToggleProvider:
    @staticmethod
    def build_set_workspace_ai_enabled_use_case() -> SetWorkspaceAiEnabledUseCase:
        from components.workspace.infrastructure.repositories.workspace_ai_toggle_repository import (
            WorkspaceAiToggleRepository,
        )

        return SetWorkspaceAiEnabledUseCase(store=WorkspaceAiToggleRepository())

"""Composition root for the workspace autonomy-mode use cases (ADR 0035 D6).

Wires the ORM-backed :class:`WorkspaceAutonomyRepository` to both use cases
(architecture-manifesto Rule 9 — providers own the port→adapter wiring). The
agents context reaches the read through its own port + adapter, which call
``build_get_workspace_autonomy_mode_use_case``.
"""

from __future__ import annotations

from components.workspace.application.use_cases.get_workspace_autonomy_mode_use_case import (
    GetWorkspaceAutonomyModeUseCase,
)
from components.workspace.application.use_cases.set_workspace_autonomy_mode_use_case import (
    SetWorkspaceAutonomyModeUseCase,
)


class WorkspaceAutonomyProvider:
    @staticmethod
    def _repository():
        from components.workspace.infrastructure.repositories.workspace_autonomy_repository import (
            WorkspaceAutonomyRepository,
        )

        return WorkspaceAutonomyRepository()

    @staticmethod
    def build_get_workspace_autonomy_mode_use_case() -> GetWorkspaceAutonomyModeUseCase:
        return GetWorkspaceAutonomyModeUseCase(store=WorkspaceAutonomyProvider._repository())

    @staticmethod
    def build_set_workspace_autonomy_mode_use_case() -> SetWorkspaceAutonomyModeUseCase:
        return SetWorkspaceAutonomyModeUseCase(store=WorkspaceAutonomyProvider._repository())

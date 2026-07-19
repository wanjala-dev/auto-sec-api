from __future__ import annotations

from typing import Protocol

from components.workspace.domain.policies.workspace_setup_policy_service import (
    WorkspaceSetupSnapshot,
)


class WorkspaceSetupQueryPort(Protocol):
    def annotate_setup_state(self, queryset):
        ...

    def build_setup_snapshot(self, workspace) -> WorkspaceSetupSnapshot:
        ...

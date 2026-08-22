"""Use case: read ``Workspace.autonomy_mode`` — the owning-context read.

The agents context enforces this policy but does not own the field, so it asks
here rather than querying a workspace model (architecture-manifesto Rule 2).

**Missing and unset are different answers.** A workspace that does not exist
returns ``None``; a workspace whose stored value is blank returns the blank
string. Collapsing them would let the enforcement side apply a real policy to a
tenant that is not there.

No Django imports — depends only on the port.
"""

from __future__ import annotations

from components.workspace.application.ports.workspace_autonomy_store_port import (
    WorkspaceAutonomyStorePort,
)


class GetWorkspaceAutonomyModeUseCase:
    def __init__(self, store: WorkspaceAutonomyStorePort) -> None:
        self._store = store

    def execute(self, *, workspace_id: str) -> str | None:
        return self._store.get_mode(str(workspace_id))

"""Repository: ``Workspace.ai_teammate_enabled`` write (implements the port).

The ORM write for the AI kill switch lives here, in the workspace context's
infrastructure — the owner of the ``Workspace`` model. Uses ``_base_manager``
(not ``.active``) so a soft-deleted workspace can still have its containment
control read/flipped, matching the manager the original inline write used.
"""

from __future__ import annotations

from components.workspace.application.ports.workspace_ai_toggle_store_port import (
    WorkspaceAiToggleResult,
    WorkspaceAiToggleStorePort,
)


class WorkspaceAiToggleRepository(WorkspaceAiToggleStorePort):
    def set_ai_enabled(self, workspace_id: str, *, enabled: bool) -> WorkspaceAiToggleResult | None:
        from infrastructure.persistence.workspaces.models import Workspace

        queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
        workspace = queryset.filter(id=str(workspace_id)).first()
        if workspace is None:
            return None

        previous = bool(workspace.ai_teammate_enabled)
        changed = previous != enabled
        if changed:
            workspace.ai_teammate_enabled = enabled
            workspace.save(update_fields=["ai_teammate_enabled"])

        return WorkspaceAiToggleResult(instance=workspace, previous=previous, changed=changed)

"""Repository: ``Workspace.autonomy_mode`` read + write (implements the port).

The ORM access for the autonomy mode lives here, in the workspace context's
infrastructure — the owner of the ``Workspace`` model.

Uses ``_base_manager`` rather than ``.active``, matching the AI kill switch
beside it and for the same reason: a soft-deleted workspace must still have its
containment controls readable. Losing sight of what a deleted tenant's agents
were permitted to do is precisely when you most want to know.
"""

from __future__ import annotations

from components.workspace.application.ports.workspace_autonomy_store_port import (
    WorkspaceAutonomyResult,
    WorkspaceAutonomyStorePort,
)


class WorkspaceAutonomyRepository(WorkspaceAutonomyStorePort):
    @staticmethod
    def _queryset():
        from infrastructure.persistence.workspaces.models import Workspace

        return getattr(Workspace, "_base_manager", None) or Workspace.objects

    def get_mode(self, workspace_id: str) -> str | None:
        row = self._queryset().filter(id=str(workspace_id)).values_list("autonomy_mode", flat=True).first()
        # A row storing an empty mode is a row we cannot interpret. Returning it
        # verbatim lets the caller's parser render UNKNOWN rather than having
        # this layer invent "assist" on its behalf.
        return None if row is None else str(row or "")

    def set_mode(self, workspace_id: str, *, mode: str) -> WorkspaceAutonomyResult | None:
        workspace = self._queryset().filter(id=str(workspace_id)).first()
        if workspace is None:
            return None

        previous = str(workspace.autonomy_mode or "")
        changed = previous != mode
        if changed:
            workspace.autonomy_mode = mode
            workspace.save(update_fields=["autonomy_mode"])

        return WorkspaceAutonomyResult(instance=workspace, previous=previous, changed=changed)

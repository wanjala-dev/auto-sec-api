"""ORM adapter for :class:`WorkspaceIdentityPort`."""

from __future__ import annotations

from components.report.application.ports.workspace_identity_port import (
    WorkspaceIdentity,
    WorkspaceIdentityPort,
)


class OrmWorkspaceIdentityAdapter(WorkspaceIdentityPort):
    def get(self, *, workspace_id: str) -> WorkspaceIdentity:
        from infrastructure.persistence.workspaces.models import Workspace

        ws = Workspace.objects.filter(id=workspace_id).first()
        if ws is None:
            return WorkspaceIdentity(workspace_id=workspace_id, name="", logo_url="")
        return WorkspaceIdentity(
            workspace_id=workspace_id,
            name=(ws.workspace_name or "").strip(),
            logo_url=(ws.photo_url or "").strip(),
        )

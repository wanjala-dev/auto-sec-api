"""ORM-backed implementation of WorkspaceAccessPort.

Reads Workspace / WorkspaceMembership / Team directly from the
persistence layer. Does not reach into another bounded context's
infrastructure — the persistence models live in ``infrastructure/``
and are shared across contexts.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from components.shared_platform.application.ports.workspace_access_port import (
    WorkspaceAccessPort,
)


class OrmWorkspaceAccessAdapter(WorkspaceAccessPort):
    """Resolve accessible workspaces for a viewer via the ORM.

    A workspace is accessible if the viewer:
      * owns it,
      * has an active WorkspaceMembership, or
      * sits on any of the workspace's Teams.
    """

    def accessible_workspace_ids(self, *, user_id: Any) -> set[str]:
        # Imports are local so the module stays importable in contexts
        # where Django apps may not yet be ready (e.g. Celery boot).
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceMembership,
        )

        if not user_id:
            return set()

        ids = (
            Workspace.objects.all_objects()
            .filter(
                Q(workspace_owner_id=user_id)
                | Q(
                    memberships__user_id=user_id,
                    memberships__status=WorkspaceMembership.Status.ACTIVE,
                )
                | Q(workspace_teams__members__id=user_id)
            )
            .values_list("id", flat=True)
            .distinct()
        )
        return {str(ws_id) for ws_id in ids}

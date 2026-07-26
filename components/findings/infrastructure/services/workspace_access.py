"""Workspace membership gate for the findings read API.

A small, boundary-clean copy (as in ``cloud_posture``): it reads the shared
``WorkspaceMembership`` persistence model — the outermost ring — rather than
importing another bounded context's service. Staff/superusers pass for support.
"""

from __future__ import annotations


def is_workspace_member(*, user, workspace_id) -> bool:
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.filter(workspace_id=workspace_id, user=user, status="active").exists()

"""Workspace membership + admin gates for the tagging API (ADR 0015 D4).

A small, boundary-clean copy (as in ``findings``): it reads the shared
``WorkspaceMembership`` persistence model — the outermost ring — rather than
importing another bounded context's service. Staff/superusers pass for support.

Gate levels (D4, grounded in the GitHub/Snyk precedents):
- ``is_workspace_member`` — create + apply/remove tags (any active member).
- ``is_workspace_admin`` — destructive *vocabulary* ops (rename/recolor/delete/
  restore): ``role in ("owner", "admin")``.
"""

from __future__ import annotations

_ADMIN_ROLES = ("owner", "admin")


def is_workspace_member(*, user, workspace_id) -> bool:
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.filter(workspace_id=workspace_id, user=user, status="active").exists()


def is_workspace_admin(*, user, workspace_id) -> bool:
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    return WorkspaceMembership.objects.filter(
        workspace_id=workspace_id, user=user, status="active", role__in=_ADMIN_ROLES
    ).exists()

"""The canonical workspace-membership gate.

Six bounded contexts (``findings``, ``cloud_graph``, ``cloud_posture``,
``response``, ``tagging``, ``shared_platform``) each carry a byte-identical
private copy of ``is_workspace_member``, every one of them documented as "a
small, boundary-clean copy". The copies exist for a real reason — a context
must not import another context's infrastructure — but the Shared Kernel is
precisely the place every context IS allowed to import from, so the copying was
never necessary.

This module is that shared home. New guards import from here; the existing six
copies are a separate, mechanical convergence (see the PR that introduced this
file). ``dry-reuse.md``: one canonical thing per concern.

The predicate matches the copies with ONE deliberate addition — the workspace
OWNER passes even without a ``WorkspaceMembership`` row:

- staff / superusers pass, for support access;
- an ``active`` ``WorkspaceMembership`` row for the pair passes;
- the workspace's own ``workspace_owner`` passes.

The owner clause is not a widening. An owner cannot meaningfully be a
non-member of their own workspace, and they already hold every right the
membership row would grant. It exists because the row is not guaranteed:
``ensure_membership`` creates one at workspace-creation time today, but
``backfill_memberships`` exists precisely because older workspaces have an
owner and no membership row. Without this clause such an owner is locked out
of their own data — a fix that produces an outage instead of a leak.

The six copies still lack the owner clause and therefore still carry that
lockout. Converging them is mechanical and tracked as follow-up; it is not
folded into a security fix.

The ORM import is function-local: the Shared Kernel is imported during app
loading, and a module-level model import would execute queries before the app
registry is ready.
"""

from __future__ import annotations

_ADMIN_ROLES = ("owner", "admin")


def _is_owner(*, user, workspace_id) -> bool:
    from infrastructure.persistence.workspaces.models import Workspace

    return Workspace.objects.filter(id=workspace_id, workspace_owner=user).exists()


def is_workspace_member(*, user, workspace_id) -> bool:
    """True when ``user`` may read this workspace's data."""
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    if WorkspaceMembership.objects.filter(workspace_id=workspace_id, user=user, status="active").exists():
        return True
    return _is_owner(user=user, workspace_id=workspace_id)


def is_workspace_admin(*, user, workspace_id) -> bool:
    """True when ``user`` may perform workspace-administrative writes."""
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    if WorkspaceMembership.objects.filter(
        workspace_id=workspace_id, user=user, status="active", role__in=_ADMIN_ROLES
    ).exists():
        return True
    return _is_owner(user=user, workspace_id=workspace_id)


__all__ = ["is_workspace_admin", "is_workspace_member"]
